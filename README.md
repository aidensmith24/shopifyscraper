# ShopifyAnalysis

A Python tool for scraping and analyzing public **Shopify store data** via the `/products.json` endpoint.  
It can collect all available products, analyze pricing, inventory, and discount patterns, and generate a **professional PDF report** complete with charts and summary tables.

---

## Features

- Automatically detects if a domain is a **Shopify store**
- Supports **proxy rotation** to reduce blocking risk
- Provides rich **data analysis** (price stats, stock, discounts, tags, keywords)
- Exports **data summaries** as structured JSON or Pandas objects
- Generates a **PDF report** with:
  - Price distribution plot  
  - Average price by vendor chart  
  - Summary tables for discounts, tags, and keywords

---

## Installation

```bash
pip install requests pandas matplotlib reportlab
```

---

## Usage

### 1. Basic scraping

```python
from shopify_analysis import ShopifyAnalysis

shop = ShopifyAnalysis("example-store.myshopify.com")
shop.scrape_all_products()
```

With proxies:

```python
proxies = ["http://123.45.67.89:8080", "http://98.76.54.32:8080"]
shop = ShopifyAnalysis("example-store.myshopify.com", proxies=proxies)
shop.scrape_all_products()
```

---

### 2. Analysis functions

```python
shop.price_summary()
shop.stock_summary()
shop.discount_summary()
shop.tag_summary()
shop.keyword_summary()
```

Example output:

```python
{
  "count": 180,
  "min": 5.0,
  "max": 120.0,
  "mean": 45.23,
  "median": 38.99
}
```

---

### 3. Generate a PDF report

```python
shop.generate_report("shopify_report.pdf")
```

**The PDF includes:**

#### Price Distribution  
![Price Distribution Example](https://via.placeholder.com/400x200.png?text=Price+Distribution)

#### Average Price by Vendor  
![Average Price by Vendor Example](https://via.placeholder.com/400x200.png?text=Average+Price+by+Vendor)

#### Summary Table Example
| Metric | Value |
|--------|--------|
| Total Products | 245 |
| Average Price | $42.10 |
| In Stock Variants | 178 |
| Estimated Inventory Value | $9,835.22 |

---

## Data Saved

All scraped product data is kept in memory (no database required).  
You can also save it manually for reuse:

```python
import json
with open("products.json", "w") as f:
    json.dump(shop.products_cache, f, indent=2)
```

---

## Limitations

- Works only with **public Shopify stores** that expose `/products.json`.  
- Pagination is supported, but Shopify’s API caps the number of items per page at 250.  
- Some stores may block automated scraping — proxies are recommended for high-volume analysis.

---

## Example Output

**Generated PDF (truncated preview)**

```
Shopify Store Analysis Report
Store: example-store.myshopify.com
Generated: 2025-10-24

Summary Statistics
──────────────────────────────
Total Products: 245
Average Price: $42.10
Median Price: $38.99
Min Price: $5.00
Max Price: $120.00
```

*(followed by charts, tag tables, and keyword summaries)*

---

## License

MIT License — free for personal and commercial use.

