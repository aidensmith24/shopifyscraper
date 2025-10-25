import os
import re
import json
import time
import random
import requests
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
from datetime import datetime
from typing import List, Dict, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
)
import tempfile


class ShopifyScraper:
    """
    Scrape and analyze public Shopify store data from /products.json endpoints.
    Includes proxy rotation, validation, analytical summaries, and PDF reporting.
    """

    def __init__(self, store_url: str, proxies: Optional[List[str]] = None, data_dir: str = "data"):
        # --- Normalize URL ---
        store_url = store_url.strip().rstrip("/")
        if "." not in store_url:
            store_url += ".myshopify.com"
        if not store_url.startswith(("http://", "https://")):
            store_url = "https://" + store_url

        self.store_url = store_url
        self.proxies = proxies or []
        self.data_dir = data_dir
        self.products_cache: List[Dict] = []

        os.makedirs(self.data_dir, exist_ok=True)

        # --- Verify Shopify before scraping ---
        if not self.is_definitely_shopify(self.store_url):
            raise ValueError(f"{self.store_url} does not appear to be a valid Shopify store.")

    # -------------------------------------------------------------------------
    # Shopify verification
    # -------------------------------------------------------------------------
    def is_definitely_shopify(self, url: str) -> bool:
        """Composite check to confirm a site is a Shopify store."""
        return (
            self._is_shopify_products_json(url)
            or self._has_shopify_headers(url)
            or self._looks_like_shopify_html(url)
        )

    def _is_shopify_products_json(self, url: str) -> bool:
        try:
            r = requests.get(f"{url}/products.json", timeout=8)
            if r.status_code == 200:
                data = r.json()
                return isinstance(data, dict) and "products" in data
        except Exception:
            pass
        return False

    def _has_shopify_headers(self, url: str) -> bool:
        try:
            r = requests.head(url, timeout=5)
            return any("shopify" in h.lower() for h in r.headers.keys())
        except Exception:
            return False

    def _looks_like_shopify_html(self, url: str) -> bool:
        try:
            r = requests.get(url, timeout=8)
            html = r.text.lower()
            return "cdn.shopify.com" in html or "shopify-digital-wallet" in html
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Core scraping
    # -------------------------------------------------------------------------
    def _get_proxy(self) -> Optional[Dict[str, str]]:
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}

    def scrape_all_products(self, limit: int = 250) -> List[Dict]:
        """Scrape all products from a Shopify store."""
        print(f"[INFO] Scraping products from {self.store_url}")
        products = []
        page = 1

        while True:
            url = f"{self.store_url}/products.json?limit={limit}&page={page}"
            proxy = self._get_proxy()

            try:
                r = requests.get(url, proxies=proxy, timeout=10)
                r.raise_for_status()
                data = r.json()
                new_products = data.get("products", [])
                if not new_products:
                    break
                products.extend(new_products)
                print(f"[INFO] Fetched page {page} ({len(new_products)} products)")
                page += 1
                time.sleep(random.uniform(0.5, 1.5))
            except Exception as e:
                print(f"[ERROR] Failed on page {page}: {e}")
                break

        self.products_cache = products
        print(f"[INFO] Total products scraped: {len(products)}")
        return products

    # -------------------------------------------------------------------------
    # Analysis
    # -------------------------------------------------------------------------
    def tag_summary(self, top_n: int = 10) -> Dict[str, int]:
        tags = Counter()
        for p in self.products_cache:
            tag_data = p.get("tags", [])
            if isinstance(tag_data, str):
                tag_list = [t.strip() for t in tag_data.split(",") if t.strip()]
            elif isinstance(tag_data, list):
                tag_list = [t.strip() for t in tag_data if isinstance(t, str) and t.strip()]
            else:
                tag_list = []
            tags.update(tag_list)
        top_tags = dict(tags.most_common(top_n))
        print(f"[INFO] Top {top_n} tags: {top_tags}")
        return top_tags

    def price_summary(self) -> Dict[str, float]:
        prices = []
        for p in self.products_cache:
            for v in p.get("variants", []):
                try:
                    prices.append(float(v.get("price", 0)))
                except (TypeError, ValueError):
                    continue

        if not prices:
            print("[WARN] No valid prices found.")
            return {}

        summary = {
            "count": len(prices),
            "min": min(prices),
            "max": max(prices),
            "mean": round(sum(prices) / len(prices), 2),
            "median": float(pd.Series(prices).median()),
        }
        print(f"[INFO] Price summary: {summary}")
        return summary

    def stock_summary(self) -> Dict[str, int]:
        total, in_stock = 0, 0
        for p in self.products_cache:
            for v in p.get("variants", []):
                total += 1
                if v.get("available", False):
                    in_stock += 1
        summary = {"total_variants": total, "in_stock": in_stock, "out_of_stock": total - in_stock}
        print(f"[INFO] Stock summary: {summary}")
        return summary

    def avg_price_by(self, field: str = "vendor") -> pd.Series:
        data = {}
        for p in self.products_cache:
            key = p.get(field, "Unknown")
            prices = [float(v.get("price", 0)) for v in p.get("variants", []) if v.get("price")]
            if prices:
                data.setdefault(key, []).extend(prices)
        avg_prices = {k: round(sum(v) / len(v), 2) for k, v in data.items()}
        df = pd.Series(avg_prices).sort_values(ascending=False)
        return df

    def discount_summary(self) -> Dict[str, float]:
        discounts = []
        for p in self.products_cache:
            for v in p.get("variants", []):
                price = float(v.get("price", 0) or 0)
                compare = float(v.get("compare_at_price") or 0)
                if compare > price > 0:
                    discount = round((compare - price) / compare * 100, 2)
                    discounts.append(discount)
        if not discounts:
            return {}
        summary = {
            "count": len(discounts),
            "avg_discount_%": round(sum(discounts) / len(discounts), 2),
            "max_discount_%": max(discounts)
        }
        return summary

    def inventory_value(self) -> float:
        total_value = 0
        for p in self.products_cache:
            for v in p.get("variants", []):
                try:
                    qty = int(v.get("inventory_quantity", 0))
                    price = float(v.get("price", 0))
                    total_value += qty * price
                except Exception:
                    continue
        return total_value

    def keyword_summary(self, top_n: int = 15) -> Dict[str, int]:
        titles = [p.get("title", "").lower() for p in self.products_cache]
        words = []
        for t in titles:
            words.extend(re.findall(r"[a-zA-Z]+", t))
        common = Counter(words)
        for w in ["the", "and", "of", "for", "a", "in"]:
            common.pop(w, None)
        return dict(common.most_common(top_n))

    # -------------------------------------------------------------------------
    # Report generation with plots
    # -------------------------------------------------------------------------
    def generate_report(self, filename: str = "shopify_report.pdf"):
        """Generate a professional PDF report summarizing product data with visualizations."""
        if not self.products_cache:
            print("[WARN] No products loaded — scrape or load a snapshot first.")
            return

        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        store_name = self.store_url.replace("https://", "").replace("http://", "")
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        story.append(Paragraph(f"<b>Shopify Store Analysis Report</b>", styles["Title"]))
        story.append(Paragraph(f"Store: {store_name}", styles["Normal"]))
        story.append(Paragraph(f"Generated: {date_str}", styles["Normal"]))
        story.append(Spacer(1, 12))

        # Summary
        price_summary = self.price_summary()
        stock_summary = self.stock_summary()
        inventory_value = self.inventory_value()

        summary_data = [
            ["Total Products", len(self.products_cache)],
            ["Average Price ($)", price_summary.get("mean", "N/A")],
            ["Median Price ($)", price_summary.get("median", "N/A")],
            ["Min Price ($)", price_summary.get("min", "N/A")],
            ["Max Price ($)", price_summary.get("max", "N/A")],
            ["In Stock Variants", stock_summary.get("in_stock", "N/A")],
            ["Out of Stock Variants", stock_summary.get("out_of_stock", "N/A")],
            ["Estimated Inventory Value ($)", f"{inventory_value:,.2f}"],
        ]

        table = Table(summary_data, colWidths=[200, 200])
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(Paragraph("<b>Summary Statistics</b>", styles["Heading2"]))
        story.append(table)
        story.append(Spacer(1, 18))

        # Price distribution plot
        prices = [float(v.get("price", 0)) for p in self.products_cache for v in p.get("variants", [])]
        if prices:
            tmp_price_plot = os.path.join(tempfile.gettempdir(), "price_distribution.png")
            plt.figure(figsize=(6, 3))
            plt.hist(prices, bins=20, edgecolor="black")
            plt.title("Price Distribution")
            plt.xlabel("Price ($)")
            plt.ylabel("Count")
            plt.grid(alpha=0.3)
            plt.tight_layout()
            plt.savefig(tmp_price_plot)
            plt.close()

            story.append(Paragraph("<b>Price Distribution</b>", styles["Heading2"]))
            story.append(Image(tmp_price_plot, width=400, height=200))
            story.append(Spacer(1, 18))

        # Average price by vendor plot
        avg_vendor = self.avg_price_by("vendor")
        if not avg_vendor.empty:
            tmp_vendor_plot = os.path.join(tempfile.gettempdir(), "avg_price_by_vendor.png")
            plt.figure(figsize=(6, 3))
            avg_vendor.plot(kind="bar", color="skyblue", edgecolor="black")
            plt.title("Average Price by Vendor")
            plt.xlabel("Vendor")
            plt.ylabel("Avg Price ($)")
            plt.xticks(rotation=45, ha="right")
            plt.grid(axis="y", alpha=0.3)
            plt.tight_layout()
            plt.savefig(tmp_vendor_plot)
            plt.close()

            story.append(Paragraph("<b>Average Price by Vendor</b>", styles["Heading2"]))
            story.append(Image(tmp_vendor_plot, width=400, height=200))
            story.append(Spacer(1, 18))

        # Discounts
        discounts = self.discount_summary()
        story.append(Paragraph("<b>Discount Summary</b>", styles["Heading2"]))
        if discounts:
            for k, v in discounts.items():
                story.append(Paragraph(f"{k.replace('_', ' ').title()}: {v}", styles["Normal"]))
        else:
            story.append(Paragraph("No discounted products found.", styles["Normal"]))
        story.append(Spacer(1, 18))

        # Tags
        tags = self.tag_summary()
        story.append(Paragraph("<b>Top Tags</b>", styles["Heading2"]))
        if tags:
            tag_data = [["Tag", "Count"]] + [[k, v] for k, v in tags.items()]
            ttable = Table(tag_data, colWidths=[250, 150])
            ttable.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            story.append(ttable)
        else:
            story.append(Paragraph("No tags available.", styles["Normal"]))
        story.append(Spacer(1, 18))

        # Keywords
        keywords = self.keyword_summary()
        story.append(Paragraph("<b>Top Keywords</b>", styles["Heading2"]))
        if keywords:
            kw_data = [["Keyword", "Count"]] + [[k, v] for k, v in keywords.items()]
            ktable = Table(kw_data, colWidths=[250, 150])
            ktable.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            story.append(ktable)
        else:
            story.append(Paragraph("No keyword data available.", styles["Normal"]))

        doc.build(story)
        print(f"[INFO] Report generated: {filename}")
