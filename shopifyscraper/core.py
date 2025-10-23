import requests
from typing import List, Dict, Optional
from urllib.parse import urljoin
import time


class ShopifyScraper:
    """
    A safe and reliable scraper for Shopify stores' products.json endpoints.
    """

    def __init__(self, shop_url: str, delay: float = 1.0, max_pages: int = 100):
        """
        Initialize the scraper.

        Args:
            shop_url (str): Base URL of the Shopify store (e.g., "https://example.myshopify.com")
            delay (float): Delay between requests (to avoid rate limits)
            max_pages (int): Maximum number of pages to fetch (safety limit)
        """
        if not shop_url.startswith("http"):
            shop_url = "https://" + shop_url
        if not shop_url.endswith("/"):
            shop_url += "/"
        self.base_url = shop_url
        self.delay = delay
        self.max_pages = max_pages

    def _get_page(self, page: int) -> Optional[Dict]:
        """
        Fetch a single page of products.json.
        Returns None if an error or empty response occurs.
        """
        url = urljoin(self.base_url, f"products.json?page={page}")
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "products" in data:
                    return data
                else:
                    print(f"[WARN] 'products' key missing in response from page {page}")
                    return None
            elif response.status_code == 429:
                print("[WARN] Rate limit hit. Waiting before retrying...")
                time.sleep(self.delay * 2)
                return self._get_page(page)  # retry once
            else:
                print(f"[ERROR] Failed to fetch page {page}: {response.status_code}")
                return None
        except requests.RequestException as e:
            print(f"[ERROR] Exception fetching page {page}: {e}")
            return None

    def scrape_all_products(self) -> List[Dict]:
        """
        Scrape all available products by iterating through pagination.
        """
        all_products = []
        page = 1

        while page <= self.max_pages:
            data = self._get_page(page)
            if not data or not data.get("products"):
                break  # stop if no more products or error
            all_products.extend(data["products"])
            print(f"[INFO] Fetched page {page} with {len(data['products'])} products.")
            page += 1
            time.sleep(self.delay)

        print(f"[DONE] Scraped {len(all_products)} total products.")
        return all_products
