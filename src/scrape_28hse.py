# src/scrape_28hse.py
import csv
import re
import sys
import time
import random
import datetime
import statistics
import os

import requests

# =====================================================================
# 1. CONFIG - district paths on 28Hse
# =====================================================================
BASE_URL = "https://www.28hse.com/rent/shop"

DISTRICTS = {
    "Sheung Wan":    "a1/dg2/di2-18",
    "Sai Ying Pun":  "a1/dg1/di1-41",
    "Causeway Bay":  "a1/dg5/di5-23",
    "Tsim Sha Tsui": "a2/dg30/di30-74",
    "Sham Shui Po":  "a2/dg26/di26-62",
}

MAX_PAGES = 12                    # safety cap per district (12 x 15 = 180 listings)
SLEEP_RANGE = (1.0, 2.0)          # random pause between requests
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-TW,zh;q=0.9",
}

FIELDS = [
    "property_id", "district", "building", "title",
    "area_sqft_gross", "area_sqft_sale", "rent_monthly",
    "rent_psf", "rent_psf_sale", "rent_psf_site", "agent_company",
    "tags", "listing_date", "update_date", "days_listed", "url", "scrape_date",
]


# =====================================================================
# 2. HELPER FUNCTIONS
# =====================================================================
def polite_sleep():
    """Pause for a random 1.0-2.0s after each request to be polite to the server."""
    time.sleep(random.uniform(*SLEEP_RANGE))


def fetch(session, url, retries=3):
    """Download one page with rate limit and exception handling."""
    for attempt in range(retries + 1):
        try:
            response = session.get(url, headers=HEADERS, timeout=20)

            if response.status_code == 429:              # rate limited
                wait = 30 * (attempt + 1)
                print(f"    [429] rate limited, sleeping {wait}s before retry")
                time.sleep(wait)
                continue

            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.RequestException as error:
            if attempt == retries:
                print(f"    [warn] failed, skipping: {url} ({error})")
                return None
            time.sleep(3)
    print(f"    [warn] still rate limited after {retries + 1} attempts: {url}")
    return None


def to_number(text):
    """'1,454' -> 1454 ; '50.2' -> 50.2 ; anything unusable -> None"""
    if not text:
        return None
    cleaned = text.replace(",", "").strip()
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return None


# =====================================================================
# 3. PARSE ONE LISTING PAGE (15 listings per page)
# =====================================================================
def parse_listing_page(html, district):
    """Turn one page of HTML into a list of dicts (one dict per shop)."""
    results = []
    blocks = html.split("property_item")[1:]     # [0] is page header noise
    for block in blocks:
        item = {}

        match = re.search(r"property-(\d+)", block)
        if not match:
            continue
        item["property_id"] = match.group(1)

        match = re.search(r'class="header[^"]*">\s*<a[^>]*>([^<]+)</a>', block)
        item["title"] = match.group(1).strip() if match else ""

        match = re.search(r"district_area[^>]*>(.*?)</div>", block, re.S)
        if match:
            names = re.findall(r"<a[^>]*>([^<]+)</a>", match.group(1))
            item["building"] = names[1].strip() if len(names) > 1 else ""
        else:
            item["building"] = ""

        item["district"] = district

        match = re.search(r"建築面積:\s*([\d,\.]+)\s*呎", block)
        item["area_sqft_gross"] = to_number(match.group(1)) if match else None

        match = re.search(r"租\s*\$([\d,\.]+)", block)
        item["rent_monthly"] = to_number(match.group(1)) if match else None

        match = re.search(r"@([\d,\.]+)\s*元", block)
        item["rent_psf_site"] = to_number(match.group(1)) if match else None

        if item["rent_monthly"] and item["area_sqft_gross"]:
            item["rent_psf"] = round(item["rent_monthly"] / item["area_sqft_gross"], 1)
        else:
            item["rent_psf"] = None

        match = re.search(r"companyName[^>]*>\s*(?:<i[^>]*>[^<]*</i>)?\s*([^<]+)<", block)
        item["agent_company"] = match.group(1).strip() if match else ""

        match = re.search(r'tagLabels">(.*?)\n\s*</div>', block, re.S)
        if match:
            tags = re.findall(r'<div class="ui\s*label">([^<]+)</div>', match.group(1))
            item["tags"] = ";".join(t.strip() for t in tags)
        else:
            item["tags"] = ""

        item["url"] = f"{BASE_URL}/property-{item['property_id']}"
        results.append(item)

    return results


# =====================================================================
# 4. PARSE ONE DETAIL PAGE
# =====================================================================
def parse_detail_page(html):
    """Return posting date, update date, gross area and saleable area."""
    info = {
        "listing_date": "",
        "update_date": "",
        "detail_area_gross": None,
        "area_sqft_sale": None,
    }
    if not html:
        return info

    match = re.search(r"刊登:(\d{4}-\d{2}-\d{2})", html)
    if match:
        info["listing_date"] = match.group(1)

    match = re.search(r"更新:(\d{4}-\d{2}-\d{2})", html)
    if match:
        info["update_date"] = match.group(1)

    match = re.search(
        r'data-key="buildArea">.*?<div class="pairValue">([\d,\.]+)\s*平方呎', html, re.S)
    if match:
        info["detail_area_gross"] = to_number(match.group(1))

    match = re.search(
        r'data-key="saleArea">.*?<div class="pairValue">([\d,\.]+)\s*平方呎', html, re.S)
    if match:
        info["area_sqft_sale"] = to_number(match.group(1))

    return info


# =====================================================================
# 5. SCRAPE ONE DISTRICT
# =====================================================================
def scrape_one_district(session, district, path, seen_ids):
    print(f"\n>>> {district}")
    collected = []

    for page in range(1, MAX_PAGES + 1):
        url = f"{BASE_URL}/{path}" if page == 1 else f"{BASE_URL}/{path}/page-{page}"

        html = fetch(session, url)
        if html is None:
            break

        page_items = parse_listing_page(html, district)

        new_items = []
        for item in page_items:
            if item["property_id"] in seen_ids:
                continue
            seen_ids.add(item["property_id"])
            new_items.append(item)

        if not new_items:
            print(f"    page {page}: no new listings, stop")
            break

        collected.extend(new_items)
        print(f"    page {page}: +{len(new_items)} (total {len(collected)})")
        polite_sleep()

    return collected


# =====================================================================
# 6. VISIT EVERY DETAIL PAGE
# =====================================================================
def add_detail_info(session, items):
    total = len(items)
    for index, item in enumerate(items, start=1):
        html = fetch(session, item["url"])
        item.update(parse_detail_page(html))
        if index % 10 == 0 or index == total:
            print(f"    detail pages {index}/{total}")
        polite_sleep()


# =====================================================================
# 7. CLEANING AND DERIVED FIELDS
# =====================================================================
def finalise_area_and_psf(items):
    for item in items:
        if item.get("detail_area_gross"):
            item["area_sqft_gross"] = item["detail_area_gross"]

        rent = item.get("rent_monthly")
        gross = item.get("area_sqft_gross")
        saleable = item.get("area_sqft_sale")

        item["rent_psf"] = round(rent / gross, 1) if rent and gross else None
        item["rent_psf_sale"] = round(rent / saleable, 1) if rent and saleable else None
    return items


def add_days_listed(items, today=None):
    today = today or datetime.date.today()
    for item in items:
        date_text = item.get("listing_date", "")
        if not date_text:
            item["days_listed"] = ""
            continue
        try:
            item["days_listed"] = (today - datetime.date.fromisoformat(date_text)).days
        except ValueError:
            item["days_listed"] = ""
    return items


def clean_records(items):
    kept, dropped = [], []
    for item in items:
        if not item.get("rent_monthly") or not item.get("area_sqft_gross"):
            dropped.append(item["property_id"])
            continue
        kept.append(item)
    print(f"Cleaning: kept {len(kept)}; dropped {len(dropped)} without rent or area")
    return kept


def validate_rent_psf(items, tolerance=0.6):
    checked = matched_gross = matched_sale = 0
    unexplained = []

    for item in items:
        site = item.get("rent_psf_site")
        if not site:
            continue
        checked += 1

        gross_psf = item.get("rent_psf")
        sale_psf = item.get("rent_psf_sale")

        if gross_psf and abs(site - gross_psf) <= tolerance:
            matched_gross += 1
            continue
        if sale_psf and abs(site - sale_psf) <= tolerance:
            matched_sale += 1
            continue
        unexplained.append((item["property_id"], site, gross_psf, sale_psf))

    print(f"\nUnit-rent cross-check ({checked} listings carry a site figure):")
    print(f"    match monthly rent / gross area    : {matched_gross}")
    print(f"    match monthly rent / saleable area : {matched_sale}")
    print(f"    unexplained anomalies              : {len(unexplained)}")
    return len(unexplained)


def write_csv(rows, path, fields):
    # 自动创建 data 目录（如果不存在）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written {path} ({len(rows)} rows)")


# =====================================================================
# 8. RENT BANDS PER DISTRICT
# =====================================================================
def summarise_by_district(rows, out_path="data/rent_by_district.csv"):
    summary = []
    for district in DISTRICTS:
        subset = [row for row in rows if row["district"] == district]
        rents = [row["rent_monthly"] for row in subset if row["rent_monthly"]]
        psf_list = [row["rent_psf"] for row in subset if row["rent_psf"]]
        if not rents:
            continue

        rent_q = statistics.quantiles(rents, n=4)

        small = [row for row in subset if row["area_sqft_gross"]
                 and 200 <= row["area_sqft_gross"] <= 800]
        small_psf = [row["rent_psf"] for row in small if row["rent_psf"]]

        summary.append({
            "district": district,
            "n_shops": len(subset),
            "rent_p25": round(rent_q[0]),
            "rent_median": round(statistics.median(rents)),
            "rent_p75": round(rent_q[2]),
            "psf_median": round(statistics.median(psf_list), 1) if psf_list else "",
            "n_small_200_800": len(small),
            "psf_median_small": round(statistics.median(small_psf), 1) if small_psf else "",
        })

    if summary:
        write_csv(summary, out_path, list(summary[0].keys()))
    return summary


# =====================================================================
# 9. MAIN
# =====================================================================
def main():
    quick = "--quick" in sys.argv
    today = datetime.date.today().isoformat()
    session = requests.Session()
    seen_ids = set()
    all_items = []

    for district, path in DISTRICTS.items():
        all_items.extend(scrape_one_district(session, district, path, seen_ids))

    if quick:
        print(f"\nList pages done: {len(all_items)} shops (quick mode)")
        for item in all_items:
            item["scrape_date"] = today
        finalise_area_and_psf(all_items)
        clean_rows = clean_records(all_items)
        write_csv(clean_rows, "data/rent_live_snapshot.csv", FIELDS)
        return

    print(f"\nList pages done: {len(all_items)} shops. Visiting detail pages ...")
    add_detail_info(session, all_items)

    for item in all_items:
        item["scrape_date"] = today

    finalise_area_and_psf(all_items)
    add_days_listed(all_items)
    validate_rent_psf(all_items)
    
    # 核心输出文件：供 Streamlit 前端网页直接读取
    write_csv(all_items, "data/rent_listings_raw.csv", FIELDS)

    clean_rows = clean_records(all_items)
    clean_rows.sort(key=lambda row: (row["district"], row["listing_date"] or ""))
    write_csv(clean_rows, "data/rent_listings_clean.csv", FIELDS)

    summarise_by_district(clean_rows)

    print(f"\nDone. Clean data saved to data/rent_listings_clean.csv")


if __name__ == "__main__":
    main()