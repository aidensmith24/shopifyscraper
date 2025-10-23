import time
import random
import itertools
from typing import List, Dict, Optional, Union
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ProxyType = Union[str, Dict[str, str]]  # "http://host:port" or {"http": "...", "https": "..."}


class ProxyUnavailable(Exception):
    pass


class ShopifyScraperSkeleton:
    """
    Robust Shopify products.json scraper with optional proxy rotation and failure handling.

    Example:
        scraper = ShopifyScraper(
            "https://example.myshopify.com",
            proxies=["http://1.2.3.4:8080", "http://user:pass@5.6.7.8:3128"],
            delay=1.0,
            timeout=10.0
        )
        products = scraper.scrape_all_products()
    """

    def __init__(
        self,
        shop_url: str,
        proxies: Optional[List[ProxyType]] = None,
        rotate_proxies: bool = True,
        delay: float = 1.0,
        timeout: float = 10.0,
        max_pages: int = 100,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        proxy_cooldown: float = 300.0,  # seconds to blacklist a failing proxy
        user_agent: Optional[str] = None,
    ):
        if not shop_url.startswith("http"):
            shop_url = "https://" + shop_url
        if not shop_url.endswith("/"):
            shop_url += "/"
        self.base_url = shop_url

        self.delay = float(delay)
        self.timeout = float(timeout)
        self.max_pages = int(max_pages)
        self.max_retries = int(max_retries)
        self.backoff_factor = float(backoff_factor)
        self.proxy_cooldown = float(proxy_cooldown)

        self.session = requests.Session()
        self._mount_retries(self.session, max_retries=max_retries, backoff_factor=backoff_factor)

        # Default headers
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": user_agent or self._random_user_agent(),
        })

        # Proxy handling structures
        self.rotate_proxies = rotate_proxies and bool(proxies)
        self._raw_proxies = proxies[:] if proxies else []
        self._proxy_cycle = itertools.cycle(self._raw_proxies) if self._raw_proxies else None
        # track failing proxies: {proxy_repr: fail_time}
        self._proxy_blacklist: Dict[str, float] = {}
        # simple failure counts
        self._proxy_fail_counts: Dict[str, int] = {}

    # ----------------------
    # Public proxy utilities
    # ----------------------
    def add_proxy(self, proxy: ProxyType) -> None:
        self._raw_proxies.append(proxy)
        self._proxy_cycle = itertools.cycle(self._raw_proxies)

    def remove_proxy(self, proxy: ProxyType) -> None:
        self._raw_proxies = [p for p in self._raw_proxies if p != proxy]
        self._proxy_cycle = itertools.cycle(self._raw_proxies) if self._raw_proxies else None
        self._proxy_blacklist.pop(self._proxy_key(proxy), None)
        self._proxy_fail_counts.pop(self._proxy_key(proxy), None)

    # ----------------------
    # Core scraping methods
    # ----------------------
    def scrape_all_products(self) -> List[Dict]:
        """
        Iterate pages and collect all products. Stops when page returns no products
        or when max_pages is reached.
        """
        all_products = []
        page = 1

        while page <= self.max_pages:
            data = self._get_page_with_retries(page)
            if not data or not data.get("products"):
                break
            products = data["products"]
            all_products.extend(products)
            print(f"[INFO] Fetched page {page} with {len(products)} products.")
            page += 1
            time.sleep(self.delay)

        print(f"[DONE] Scraped {len(all_products)} total products.")
        return all_products

    def _get_page_with_retries(self, page: int) -> Optional[Dict]:
        """
        Wrapper that handles retries, rate-limits (429), backoff, and proxy rotation.
        """
        url = urljoin(self.base_url, f"products.json?page={page}")
        attempt = 0
        while attempt < self.max_retries:
            attempt += 1
            try:
                resp = self._request("GET", url)
                if resp is None:
                    # network/proxy failure: try again (next proxy or backoff)
                    raise requests.RequestException("No response received (proxy/network error).")
                if resp.status_code == 200:
                    data = resp.json()
                    if "products" not in data:
                        print(f"[WARN] 'products' key missing in response for page {page}")
                        return None
                    return data
                elif resp.status_code == 429:
                    wait = self.backoff_factor * (2 ** (attempt - 1))
                    print(f"[WARN] 429 rate limited. Sleeping {wait:.1f}s and retrying...")
                    time.sleep(wait)
                    continue
                elif 500 <= resp.status_code < 600:
                    wait = self.backoff_factor * (2 ** (attempt - 1))
                    print(f"[WARN] Server error {resp.status_code}. Sleeping {wait:.1f}s then retrying...")
                    time.sleep(wait)
                    continue
                else:
                    print(f"[ERROR] Unexpected status {resp.status_code} for page {page}")
                    return None
            except requests.RequestException as e:
                wait = self.backoff_factor * (2 ** (attempt - 1))
                print(f"[WARN] Request exception: {e}. Backing off {wait:.1f}s then retrying...")
                time.sleep(wait)
                continue

        print(f"[ERROR] Exhausted retries for page {page}")
        return None

    # ----------------------
    # HTTP + Proxy management
    # ----------------------
    def _request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """
        Performs a single HTTP request. If proxies are configured and rotation enabled,
        select a proxy and try; on proxy failure mark proxy as failing and rotate.
        Returns requests.Response or None on fatal network/proxy error.
        """
        kwargs.setdefault("timeout", self.timeout)

        # If no proxies are configured, simple request
        if not self._raw_proxies:
            try:
                return self.session.request(method, url, **kwargs)
            except requests.RequestException as e:
                print(f"[ERROR] Request failed without proxy: {e}")
                return None

        # Try a number of proxies (up to count of proxies)
        proxies_tried = 0
        max_try = max(1, len(self._raw_proxies))
        while proxies_tried < max_try:
            proxy = self._get_next_proxy()
            if proxy is None:
                # no proxies available (all blacklisted)
                raise ProxyUnavailable("No available proxies (all blacklisted).")
            proxy_key = self._proxy_key(proxy)

            # Skip blacklisted proxies
            if self._is_blacklisted(proxy_key):
                proxies_tried += 1
                continue

            proxy_dict = self._normalize_proxy(proxy)
            try:
                resp = self.session.request(method, url, proxies=proxy_dict, **kwargs)
                # If proxy returned 403/407/5xx connection errors, treat as proxy failure
                if resp.status_code in (502, 503, 504):
                    self._record_proxy_failure(proxy_key)
                    proxies_tried += 1
                    print(f"[WARN] Proxy {proxy_key} produced {resp.status_code}; trying next proxy.")
                    continue
                # success (including 200/404/429)
                # reset fail count on successful proxy response
                self._proxy_fail_counts.pop(proxy_key, None)
                return resp
            except requests.ProxyError as e:
                # proxy connection problem -> mark and try next
                self._record_proxy_failure(proxy_key)
                proxies_tried += 1
                print(f"[WARN] ProxyError with {proxy_key}: {e}. Trying next proxy.")
                continue
            except requests.RequestException as e:
                # network error - could be proxy or remote; mark proxy as failed conservatively
                self._record_proxy_failure(proxy_key)
                proxies_tried += 1
                print(f"[WARN] RequestException with {proxy_key}: {e}. Trying next proxy.")
                continue

        # if we reach here, all proxies tried & failed
        print("[ERROR] All proxies tried and failed for this request.")
        return None

    # ----------------------
    # Proxy helpers
    # ----------------------
    def _get_next_proxy(self) -> Optional[ProxyType]:
        if not self._raw_proxies:
            return None
        if not self.rotate_proxies:
            return self._raw_proxies[0]
        # rotate until we find a non-blacklisted proxy or exhausted
        for _ in range(len(self._raw_proxies)):
            try:
                p = next(self._proxy_cycle)
            except Exception:
                # rebuild cycle if needed
                self._proxy_cycle = itertools.cycle(self._raw_proxies)
                p = next(self._proxy_cycle)
            if not self._is_blacklisted(self._proxy_key(p)):
                return p
        return None  # all blacklisted

    def _proxy_key(self, proxy: ProxyType) -> str:
        # generate a simple key to identify a proxy (stringify)
        if isinstance(proxy, dict):
            return repr(proxy)
        return str(proxy)

    def _is_blacklisted(self, proxy_key: str) -> bool:
        t = self._proxy_blacklist.get(proxy_key)
        if not t:
            return False
        # if cooldown expired, remove from blacklist
        if time.time() - t > self.proxy_cooldown:
            self._proxy_blacklist.pop(proxy_key, None)
            self._proxy_fail_counts.pop(proxy_key, None)
            return False
        return True

    def _record_proxy_failure(self, proxy_key: str) -> None:
        # increment fail count; blacklist if threshold exceeded
        cnt = self._proxy_fail_counts.get(proxy_key, 0) + 1
        self._proxy_fail_counts[proxy_key] = cnt
        # threshold: 2 failures -> temporary blacklist
        if cnt >= 2:
            self._proxy_blacklist[proxy_key] = time.time()
            print(f"[WARN] Blacklisting proxy {proxy_key} for {self.proxy_cooldown}s due to repeated failures.")

    def _normalize_proxy(self, proxy: ProxyType) -> Dict[str, str]:
        """
        Convert proxy spec into requests-style proxies dict.
        Accepts:
            - string "http://host:port"
            - dict {"http": "...", "https": "..."}
        Returns proxies dict for requests.
        """
        if isinstance(proxy, dict):
            return proxy
        # assume string; apply to both http and https
        return {"http": proxy, "https": proxy}

    # ----------------------
    # Utilities
    # ----------------------
    def _mount_retries(self, session: requests.Session, max_retries: int = 3, backoff_factor: float = 0.5) -> None:
        """
        Mount HTTPAdapter that retries on connection errors.
        """
        retries = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"]),
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

    def _random_user_agent(self) -> str:
        # Simple small pool; in production you could expand or accept user-specified UA.
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
            " Chrome/117.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/605.1.15 (KHTML, like Gecko)"
            " Version/16.0 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
            " Chrome/117.0.0.0 Safari/537.36",
        ]
        return random.choice(uas)

import pandas as pd
from statistics import mean, median
from collections import Counter

class ShopifyScraper(ShopifyScraperSkeleton):
    """
    Extends ShopifyScraper with analysis capabilities.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.products_cache: list = []

    # ----------------------
    # Cache products for analysis
    # ----------------------
    def scrape_and_cache(self) -> None:
        self.products_cache = self.scrape_all_products()

    # ----------------------
    # Price analysis
    # ----------------------
    def price_summary(self) -> dict:
        if not self.products_cache:
            raise ValueError("No products cached. Call scrape_and_cache() first.")

        prices = []
        for p in self.products_cache:
            for variant in p.get("variants", []):
                try:
                    prices.append(float(variant.get("price", 0)))
                except ValueError:
                    continue

        if not prices:
            return {}

        return {
            "count": len(prices),
            "min": min(prices),
            "max": max(prices),
            "mean": mean(prices),
            "median": median(prices),
        }

    # ----------------------
    # Inventory / stock analysis
    # ----------------------
    def stock_summary(self) -> dict:
        """
        Summarizes stock availability (in-stock vs out-of-stock) based on the 'available' field.
        This works even when inventory_quantity is not publicly available.
        """
        if not self.products_cache:
            raise ValueError("No products cached. Call scrape_and_cache() first.")

        in_stock = 0
        out_of_stock = 0
        unavailable_products = []

        for p in self.products_cache:
            for v in p.get("variants", []):
                if v.get("available", False):
                    in_stock += 1
                else:
                    out_of_stock += 1
                    unavailable_products.append({
                        "id": p.get("id"),
                        "title": p.get("title"),
                        "variant": v.get("title"),
                    })

        return {
            "in_stock_variants": in_stock,
            "out_of_stock_variants": out_of_stock,
            "out_of_stock_products": unavailable_products
        }

    # ----------------------
    # Products by vendor / type
    # ----------------------
    def count_by_field(self, field: str = "vendor") -> dict:
        counter = Counter()
        for p in self.products_cache:
            key = p.get(field, "Unknown")
            counter[key] += 1
        return dict(counter)

    # ----------------------
    # Variant analysis
    # ----------------------
    def variant_summary(self) -> dict:
        variant_counts = []
        option_counter = Counter()
        for p in self.products_cache:
            variants = p.get("variants", [])
            variant_counts.append(len(variants))
            for v in variants:
                for opt in v.get("option1"), v.get("option2"), v.get("option3"):
                    if opt:
                        option_counter[opt] += 1
        return {
            "min_variants": min(variant_counts) if variant_counts else 0,
            "max_variants": max(variant_counts) if variant_counts else 0,
            "mean_variants": mean(variant_counts) if variant_counts else 0,
            "most_common_options": option_counter.most_common(10)
        }

    # ----------------------
    # Export cached products to CSV / JSON
    # ----------------------
    def export_products(self, filename: str, file_type: str = "csv") -> None:
        if not self.products_cache:
            raise ValueError("No products cached. Call scrape_and_cache() first.")

        df = pd.json_normalize(self.products_cache, sep="_")
        if file_type.lower() == "csv":
            df.to_csv(filename, index=False)
        elif file_type.lower() == "json":
            df.to_json(filename, orient="records", indent=4)
        else:
            raise ValueError("file_type must be 'csv' or 'json'.")
