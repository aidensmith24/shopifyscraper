# ShopifyAnalysis

A Python tool for scraping and analyzing Shopify store product data.

---

## Overview

**ShopifyAnalysis** scrapes public product data from any Shopify store’s `/products.json` endpoint and provides useful analytics and visualizations.

It supports:
- Proxy rotation to avoid bans or rate limits  
- Automatic URL normalization (`mystore` → `https://mystore.myshopify.com`)  
- Tag, vendor, and price analysis  
- Stock availability summaries  
- Snapshot saving for historical tracking  
- Simple trend comparison between saved snapshots  
- Visualizations with Matplotlib  

---

## Features

| Category | Description |
|-----------|-------------|
| Scraping | Paginated scraping from `/products.json` |
| Proxies | Optional proxy rotation per request |
| Analysis | Tag frequency, price stats, stock summary |
| Visualization | Price histogram, vendor/type bar chart |
| Snapshots | Save and load JSON snapshots of products |
| Trend Tracking | Compare two snapshots for added/removed/changed products |
| Smart Input | Accepts just a shop name or domain, no need for `https://` |

---

## Installation

```bash
pip install requests pandas matplotlib
```

Or clone this repository and work directly with the Python file:

```bash
git clone https://github.com/yourusername/shopify-analysis.git
cd shopify-analysis
```

---

## Example Usage

```python
from shopifyscraper import ShopifyScraper

# Initialize (no need for "https://")
scraper = ShopifyScraper("mystore.myshopify.com", proxies=[
    "http://user:pass@proxy1:port",
    "http://proxy2:port"
])

# 1. Scrape and save a snapshot
scraper.scrape_all_products()
scraper.save_snapshot()  # Saves to data/products_YYYY-MM-DD.json

# 2. Analyze
scraper.tag_summary()
scraper.price_summary()
print(scraper.stock_summary())

# 3. Visualize
scraper.plot_price_distribution()
scraper.plot_distribution("vendor")

# 4. Compare snapshots
diff = scraper.compare_snapshots(
    "data/products_2025-10-20.json",
    "data/products_2025-10-23.json"
)
print(diff)
```

---

## Example Outputs

**Tag Summary**
```
[INFO] Top 10 tags: {'T-Shirts': 14, 'Sale': 9, 'Hoodies': 6}
```

**Price Summary**
```
[INFO] Price summary: {'count': 128, 'min': 9.99, 'max': 79.95, 'mean': 34.2, 'median': 29.95}
```

**Trend Comparison**
```
[INFO] Changes since last snapshot: {
  'added': ['New Hoodie'],
  'removed': ['Old Beanie'],
  'changed': ['Logo Tee']
}
```

---

## Project Structure

```
shopify-analysis/
│
├── shopify_analysis.py      # main class (ShopifyAnalysis)
├── data/                    # saved product snapshots
└── README.md
```

---

## Disclaimer

This tool accesses publicly available Shopify data via `/products.json`.  
Use it responsibly. Do not overload or abuse store servers.  
Always comply with each website’s terms of service and local laws.

---

## Author

Developed by [Your Name] — 2025  
MIT License