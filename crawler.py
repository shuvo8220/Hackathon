"""
ROC Bangladesh - Form Crawler
==============================
roc.gov.bd Downloads page theke sob form HTML download kore
roc_forms_html_storage/ folder e save kore.

Run: hack\Scripts\python.exe crawler.py
"""

import re
import time
from pathlib import Path
from urllib.parse import urljoin

BASE_DIR     = Path(__file__).parent
HTML_STORAGE = BASE_DIR / "roc_forms_html_storage"
HTML_STORAGE.mkdir(exist_ok=True)

ROC_BASE_URL  = "https://app.roc.gov.bd"
DOWNLOAD_PAGE = f"{ROC_BASE_URL}/Guidlines/Download/Downloads.html"

ENTITY_TYPE_MAP = {
    "private company":    "private_limited",
    "public company":     "public_limited",
    "trade organization": "trade_organization",
    "society":            "ngo",
    "foreign company":    "foreign_company",
    "partnership":        "partnership",
    "sole":               "sole_proprietorship",
}

def get_btype(entity_text: str) -> str:
    et = entity_text.lower()
    for key, val in ENTITY_TYPE_MAP.items():
        if key in et:
            return val
    return "general"

def clean_filename(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9]", "_", text[:50])).strip("_").lower()

def crawl_and_save_html():
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print("Run: pip install playwright beautifulsoup4 && playwright install chromium")
        return

    print(f"Loading: {DOWNLOAD_PAGE}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()

        try:
            page.goto(DOWNLOAD_PAGE, timeout=60000)
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Error: {e}")
            return

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page.content(), "html.parser")
        rows = soup.find_all("tr")
        print(f"Found {len(rows)} table rows")

        # Parse table: Process | Entity Type | Documents
        forms = []
        current_process = ""
        current_entity  = ""

        for row in rows:
            cols = row.find_all(["td", "th"])
            if not cols:
                continue
            proc = cols[0].get_text(strip=True) if len(cols) > 0 else ""
            if proc:
                current_process = proc
            ent = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            if ent:
                current_entity = ent
            if len(cols) < 3:
                continue
            for link in cols[2].find_all("a", href=True):
                title = link.get_text(strip=True)
                href  = link["href"]
                if not title or not href:
                    continue
                full_url = urljoin(DOWNLOAD_PAGE, href)
                forms.append({
                    "process": current_process,
                    "entity":  current_entity,
                    "title":   title,
                    "url":     full_url
                })

        print(f"Found {len(forms)} form links\n")
        total = saved = 0

        for item in forms:
            total += 1
            btype    = get_btype(item["entity"])
            filename = clean_filename(item["title"]) + ".html"
            save_dir = HTML_STORAGE / btype
            save_dir.mkdir(parents=True, exist_ok=True)
            out_path = save_dir / filename

            print(f"  [{total}] {item['title']}")

            try:
                page.goto(item["url"], timeout=30000)
                page.wait_for_load_state("networkidle")

                from bs4 import BeautifulSoup as BS
                form_soup = BS(page.content(), "html.parser")
                for tag in form_soup(["script", "style"]):
                    tag.decompose()

                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(f"<!-- Source: {item['url']} -->\n")
                    f.write(f"<!-- Process: {item['process']} -->\n")
                    f.write(str(form_soup))

                print(f"      Saved: {btype}/{filename}")
                saved += 1
            except Exception as e:
                print(f"      ERR: {e}")

            time.sleep(0.5)

        browser.close()
        print(f"\nDone! {saved}/{total} forms saved to {HTML_STORAGE}")

if __name__ == "__main__":
    crawl_and_save_html()
