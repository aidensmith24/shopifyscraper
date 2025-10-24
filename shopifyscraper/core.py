import os
import json
import time
import random
import requests
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
from statistics import mean, median
from typing import Dict, List, Optional


class ShopifyScraper:
    """
    A full-featured Shopify product scraper and analytics tool.
    Capabilities:
    - Scrapes all products from a Shopify store (using proxy rotation if configured)
    - Performs tag, vendor, and price analysis
    - Saves daily snapshots for trend tracking
    - Generates visualizations (price distribution, vendor breakdown)
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
        """Check if /products.json exists and returns valid JSON."""
        try:
            r = requests.get(f"{url}/products.json", timeout=8)
            if r.status_code == 200:
                data = r.json()
                return isinstance(data, dict) and "products" in data
        except Exception:
            pass
        return False

    def _has_shopify_headers(self, url: str) -> bool:
        """Check for Shopify-specific response headers."""
        try:
            r = requests.head(url, timeout=5)
            return any("shopify" in h.lower() for h in r.headers.keys())
        except Exception:
            return False

    def _looks_like_shopify_html(self, url: str) -> bool:
        """Look for Shopify-specific HTML markers."""
        try:
            r = requests.get(url, timeout=8)
            html = r.text.lower()
            return "cdn.shopify.com" in html or "shopify-digital-wallet" in html
        except Exception:
            return False
   
    def _get_proxy(self) -> Optional[Dict[str, str]]:
        """Returns a random proxy (if any available)."""
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}

    def _fetch_page(self, page: int = 1) -> Optional[List[Dict]]:
        """Fetches one page of products.json."""
        url = f"{self.store_url}/products.json?page={page}&limit=250"
        try:
            response = requests.get(url, proxies=self._get_proxy(), timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("products", [])
        except Exception as e:
            print(f"[WARN] Failed to fetch page {page}: {e}")
            return None

    def scrape_all_products(self) -> List[Dict]:
        """Fetches all products across paginated JSON pages."""
        products = []
        page = 1
        print(f"[INFO] Starting scrape for {self.store_url}")
        while True:
            page_data = self._fetch_page(page)
            if not page_data:
                break
            products.extend(page_data)
            print(f"[INFO] Page {page}: {len(page_data)} products")
            page += 1
            if len(page_data) < 250:
                break
            time.sleep(1)  # be polite
        print(f"[INFO] Scraped total {len(products)} products.")
        self.products_cache = products
        return products

    def save_snapshot(self, filename: Optional[str] = None) -> str:
        """Saves current product cache to timestamped JSON file."""
        if not self.products_cache:
            raise ValueError("No products cached. Run scrape_all_products() first.")

        if not filename:
            date = time.strftime("%Y-%m-%d")
            filename = os.path.join(self.data_dir, f"products_{date}.json")

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.products_cache, f, indent=2)
        print(f"[INFO] Snapshot saved: {filename}")
        return filename

    def load_snapshot(self, filename: str) -> None:
        """Loads product data from a saved snapshot."""
        with open(filename, "r", encoding="utf-8") as f:
            self.products_cache = json.load(f)
        print(f"[INFO] Loaded snapshot: {filename}")

    def tag_summary(self, top_n: int = 10) -> Dict[str, int]:
        """Returns the most common tags across products (handles string or list formats)."""
        tags = Counter()
        for p in self.products_cache:
            tag_data = p.get("tags", [])
            
            # Normalize: ensure we always have a list
            if isinstance(tag_data, str):
                tag_list = [t.strip() for t in tag_data.split(",") if t.strip()]
            elif isinstance(tag_data, list):
                tag_list = [t.strip() for t in tag_data if isinstance(t, str) and t.strip()]
            else:
                tag_list = []

            for tag in tag_list:
                tags[tag] += 1

        top_tags = dict(tags.most_common(top_n))
        print(f"[INFO] Top {top_n} tags: {top_tags}")
        return top_tags


    def price_summary(self) -> Dict[str, float]:
        """Returns basic statistics about variant prices."""
        prices = []
        for p in self.products_cache:
            for v in p.get("variants", []):
                try:
                    prices.append(float(v.get("price", 0)))
                except (ValueError, TypeError):
                    continue

        if not prices:
            print("[WARN] No prices found.")
            return {}

        stats = {
            "count": len(prices),
            "min": min(prices),
            "max": max(prices),
            "mean": mean(prices),
            "median": median(prices),
        }
        print(f"[INFO] Price summary: {stats}")
        return stats

    def stock_summary(self) -> Dict[str, int]:
        """Estimates stock availability (based on variant 'available' flag)."""
        available, unavailable = 0, 0
        for p in self.products_cache:
            for v in p.get("variants", []):
                if v.get("available", False):
                    available += 1
                else:
                    unavailable += 1
        return {"available": available, "unavailable": unavailable}

    def plot_price_distribution(self, bins: int = 20):
        """Plots histogram of variant prices."""
        prices = [
            float(v["price"])
            for p in self.products_cache
            for v in p.get("variants", [])
            if v.get("price")
        ]
        if not prices:
            print("[WARN] No price data to plot.")
            return

        plt.figure(figsize=(8, 5))
        plt.hist(prices, bins=bins, alpha=0.7)
        plt.title("Price Distribution")
        plt.xlabel("Price")
        plt.ylabel("Number of Variants")
        plt.grid(True, alpha=0.3)
        plt.show()

    def plot_distribution(self, field: str = "vendor", top_n: int = 10):
        """Plots a bar chart of top vendors or product types."""
        counter = Counter()
        for p in self.products_cache:
            key = p.get(field) or "Unknown"
            counter[key] += 1
        top = dict(counter.most_common(top_n))

        plt.figure(figsize=(10, 5))
        plt.bar(top.keys(), top.values(), alpha=0.7)
        plt.title(f"Top {top_n} {field.title()}s")
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("Product Count")
        plt.tight_layout()
        plt.show()

    def compare_snapshots(self, old_file: str, new_file: str) -> Dict[str, List[str]]:
        """Compare two saved snapshots to find added, removed, or changed products."""
        def load_products(path):
            with open(path, "r", encoding="utf-8") as f:
                return {str(p["id"]): p for p in json.load(f)}

        old = load_products(old_file)
        new = load_products(new_file)

        old_ids = set(old.keys())
        new_ids = set(new.keys())

        added = new_ids - old_ids
        removed = old_ids - new_ids
        changed = [pid for pid in old_ids & new_ids if old[pid] != new[pid]]

        result = {
            "added": [new[i]["title"] for i in added],
            "removed": [old[i]["title"] for i in removed],
            "changed": [new[i]["title"] for i in changed],
        }
        print(f"[INFO] Changes since last snapshot: {result}")
        return result
