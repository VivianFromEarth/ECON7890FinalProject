#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECON7890 Group project - Member 1 (OpenRice Coffee Shop Crawler)
Scrape information on all coffee shops in five districts of Hong Kong, along with all customer reviews for these shops.

Usage
-----
    pip install requests
    python3 openrice_crawler.py

Data source
-----------
Both pages are filled in by JSON endpoints, so we call them:
    GET https://www.openrice.com/api/v2/search?districtId=1001&amenityId=1008&startAt=0&rows=50
    GET https://www.openrice.com/api/v2/review?poiId=693758&startAt=0&rows=200

“count” in each response is used to check that no page was missed.

Outputs
-----------------------------------
    data/shops.csv        one row per shop             29 columns
    data/reviews.csv      one row per review           13 columns
    data/combined.csv     review + shop attributes     22 columns
    raw/shops/*.json      raw search responses         (audit / rebuild)
    raw/reviews/{id}.json raw review responses         (resume support)

Field notes
-----------
* Shop "score_overall" is 0-5; review "score_overall" is 0-50. "score_stars" is the
  review score / 10, so it matches the shop scale.
* Per-capita spending is a band ("priceRangeId" 1-6): "price_band" is the label,
  "price_mid_hkd" the band midpoint (not actual spending).
* smile_ratio = positive / (positive + negative) votes; blank when there are no votes.
* No opening date -> open_year / years_open blank, not 0.
* is_chain_suspect is inferred (base name appears >= 3 times), not official.

Politeness
----------
2 seconds between requests; 403/429 triggers a longer wait and a retry.
A full run is a few hundred requests and 30-60 minutes, mostly waiting.
"""

import csv
import json
import random
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests

# ============================================================
# 1. Settings
# ============================================================
DISTRICTS = [
    {"zh": "上環", "en": "Sheung Wan", "slug": "sheung-wan", "id": 1001},
    {"zh": "西營盤", "en": "Sai Ying Pun", "slug": "sai-ying-pun", "id": -35244},
    {"zh": "銅鑼灣", "en": "Causeway Bay", "slug": "causeway-bay", "id": 1019},
    {"zh": "尖沙咀", "en": "Tsim Sha Tsui", "slug": "tsim-sha-tsui", "id": 2008},
    {"zh": "深水埗", "en": "Sham Shui Po", "slug": "sham-shui-po", "id": 2019},
]

ONLY_DISTRICT = ""          # scrape one district only, using its Chinese name (e.g. "深水埗"); "" = all districts
MAX_SHOPS_FOR_REVIEWS = 0   # fetch reviews for the top N shops only, ranked by review count; 0 = all shops
MAX_REVIEWS_PER_SHOP = 0    # keep at most N reviews per shop; 0 = all reviews
REFRESH_CACHE = False       # True = ignore the raw/ cache and re-download everything
OFFLINE_REBUILD = False     # True = no network; rebuild the three CSVs from raw/ alone

SEARCH_URL = "https://www.openrice.com/api/v2/search"
REVIEW_URL = "https://www.openrice.com/api/v2/review"
AMENITY_COFFEE = 1008
SHOP_PAGE_SIZE = 50
REVIEW_PAGE_SIZE = 200

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.openrice.com/zh/hongkong/restaurants",
}

REQUEST_GAP = 2.0
MAX_RETRIES = 3

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_SHOP_DIR = HERE / "raw" / "shops"
RAW_REVIEW_DIR = HERE / "raw" / "reviews"

PRICE_BANDS = {
    1: ("$50以下", 25),
    2: ("$51-100", 75),
    3: ("$101-200", 150),
    4: ("$201-400", 300),
    5: ("$401-800", 600),
    6: ("$801以上", 1000),
}

SHOP_COLUMNS = [
    "poi_id", "name", "name_en", "district", "district_en", "district_api",
    "street", "street_clean", "address_tc", "address_en",
    "open_since", "open_year", "years_open",
    "price_range_id", "price_band", "price_mid_hkd",
    "score_overall", "n_smile", "n_cry", "n_review", "smile_ratio",
    "n_photo", "n_bookmark", "cuisines", "tags",
    "is_chain_suspect", "chain_name", "detail_url", "scraped_at",
]

REVIEW_COLUMNS = [
    "poi_id", "shop_name", "district", "review_id",
    "score_overall", "score_stars",
    "title", "body", "text", "text_len",
    "n_photo", "like_count", "submit_time",
]

COMBINED_COLUMNS = REVIEW_COLUMNS + [
    "shop_score_overall", "shop_n_review", "price_band", "price_mid_hkd",
    "street_clean", "open_year", "years_open",
    "is_chain_suspect", "cuisines",
]

# ============================================================
# 2. HTTP
# ============================================================

def fetch_json(url, params):
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(REQUEST_GAP + random.uniform(0, 0.6))

        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=40)
        except requests.RequestException as exc:
            print(f"network error ({exc.__class__.__name__}), retry {attempt}/{MAX_RETRIES}")
            time.sleep(5 * attempt)
            continue

        if response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError:
                print("got HTML instead of JSON (probably a verification page)")
                time.sleep(30)
                continue

        if response.status_code in (403, 429):
            wait = 60 if attempt < MAX_RETRIES else 0
            print(f"HTTP {response.status_code} (rate limited), wait {wait}s")
            time.sleep(wait)
            continue

        print(f"HTTP {response.status_code}, retry {attempt}/{MAX_RETRIES}")
        time.sleep(5 * attempt)

    return None

# ============================================================
# 3. Shops
# ============================================================

def street_from_address(address):
    if not address:
        return ""
    match = re.match(r"^([^\d0-9]+?)(?:\d|$)", address)
    street = match.group(1).strip() if match else ""
    return street if 2 <= len(street) <= 20 else ""


def clean_street(street, district):
    if street.startswith(district) and len(street) - len(district) >= 2:
        return street[len(district):]
    return street


def parse_shop(poi, district, scraped_at):
    address = (poi.get("address") or "").strip()
    street = street_from_address(address)

    open_since = (poi.get("openSince") or "")[:10]
    open_year = None
    years_open = None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", open_since):
        opened = datetime.strptime(open_since, "%Y-%m-%d").date()
        open_year = opened.year
        years_open = round((date.today() - opened).days / 365.25, 1)
    elif open_since[:4].isdigit():
        open_year = int(open_since[:4])
        years_open = round((date.today() - date(open_year, 1, 1)).days / 365.25, 1)

    price_id = poi.get("priceRangeId")
    price_band, price_mid = PRICE_BANDS.get(price_id, ("", ""))

    n_smile = poi.get("scoreSmile") or 0
    n_cry = poi.get("scoreCry") or 0
    smile_ratio = round(n_smile / (n_smile + n_cry), 4) if (n_smile + n_cry) else ""

    return {
        "poi_id": poi.get("poiId"),
        "name": (poi.get("name") or "").strip(),
        "name_en": (poi.get("nameOtherLang") or "").strip(),
        "district": district["zh"],
        "district_en": district["en"],
        "district_api": (poi.get("district") or {}).get("name", ""),
        "street": street,
        "street_clean": clean_street(street, district["zh"]),
        "address_tc": address,
        "address_en": (poi.get("addressOtherLang") or "").strip(),
        "open_since": open_since,
        "open_year": open_year,
        "years_open": years_open,
        "price_range_id": price_id,
        "price_band": price_band,
        "price_mid_hkd": price_mid,
        "score_overall": poi.get("scoreOverall"),    # 0-5
        "n_smile": n_smile,
        "n_cry": n_cry,
        "n_review": poi.get("reviewCount") or 0,
        "smile_ratio": smile_ratio,
        "n_photo": poi.get("photoCount"),
        "n_bookmark": poi.get("bookmarkedUserCount"),
        "cuisines": "|".join(c.get("name", "") for c in poi.get("categories") or []),
        "tags": "|".join(t.get("name", "") for t in poi.get("tags") or []),
        "is_chain_suspect": False,
        "chain_name": "",
        "detail_url": "https://www.openrice.com/zh/hongkong/r-x-r" + str(poi.get("poiId")),
        "scraped_at": scraped_at,
    }


def scrape_district(district, scraped_at):
    shops = []
    seen = set()
    start = 0
    total = 0

    while True:
        cache_file = RAW_SHOP_DIR / f"{district['slug']}-{start:03d}.json"

        if cache_file.exists() and not REFRESH_CACHE:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            payload = fetch_json(SEARCH_URL, {
                "uiLang": "zh",
                "uiCity": "hongkong",
                "districtId": district["id"],
                "amenityId": AMENITY_COFFEE,
                "startAt": start,
                "rows": SHOP_PAGE_SIZE,
            })
            if payload is None:
                break
            RAW_SHOP_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        result = payload.get("paginationResult") or {}
        total = result.get("count", 0)
        items = result.get("results") or []
        if not items:
            break

        new_rows = 0
        for poi in items:
            row = parse_shop(poi, district, scraped_at)
            if row["poi_id"] in seen:      # The ad placement will list the same store twice.
                continue
            seen.add(row["poi_id"])
            shops.append(row)
            new_rows += 1

        print(f"page {start // SHOP_PAGE_SIZE + 1}: +{new_rows}, total {len(shops)}/{total}")

        start += SHOP_PAGE_SIZE
        if start >= total:
            break

    return shops, total


def detect_chains(shops):
    def base_name(name):
        return re.sub(r"\s*[\(（].*?[\)）]\s*$", "", name).strip().lower() # Remove the branch name in the parentheses at the end of the store name.

    counts = {}
    for shop in shops:
        key = base_name(shop["name"])
        counts[key] = counts.get(key, 0) + 1

    for shop in shops:
        key = base_name(shop["name"])
        if counts.get(key, 0) >= 3:   # Many independent shops in Hong Kong open a second branch, but only when they have three or more locations do they really start to look like a chain.
            shop["is_chain_suspect"] = True
            shop["chain_name"] = key


# ============================================================
# 4. Reviews
# ============================================================

def clean_review_text(title, body):
    title = (title or "").strip()
    body = (body or "").strip()
    text = f"{title}。{body}" if title else body
    text = re.sub(r"\[/?url[^\]]*\]", "", text)
    text = re.sub(r"\[/?[bi]\]", "", text)
    text = re.sub(r"\[IMG:\d+\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" 。")


def fetch_reviews(shop):
    cache_file = RAW_REVIEW_DIR / f"{shop['poi_id']}.json"

    if cache_file.exists() and not REFRESH_CACHE:
        return json.loads(cache_file.read_text(encoding="utf-8")), True

    collected = []
    start = 0

    while True:
        data = fetch_json(REVIEW_URL, {
            "poiId": shop["poi_id"],
            "startAt": start,
            "rows": REVIEW_PAGE_SIZE,
        })
        if data is None:
            break

        items = data.get("results") or []
        if not items:
            break

        collected.extend(items)
        start += len(items)

        if MAX_REVIEWS_PER_SHOP and len(collected) >= MAX_REVIEWS_PER_SHOP:
            collected = collected[:MAX_REVIEWS_PER_SHOP]
            break
        if start >= (data.get("count") or 0):
            break

    keep = ["reviewId", "scoreOverall", "title", "body", "submitTime",
            "photoCount", "ratingUpCount"]
    trimmed = [{k: r.get(k) for k in keep} for r in collected]

    RAW_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")
    return trimmed, False


def build_review_rows(shop, raw_reviews):
    rows = []
    for review in raw_reviews:
        title = (review.get("title") or "").strip()
        body = (review.get("body") or "").strip()
        text = clean_review_text(title, body)

        score_50 = review.get("scoreOverall")
        stars = round(score_50 / 10, 1) if score_50 is not None else ""

        rows.append({
            "poi_id": shop["poi_id"],
            "shop_name": shop["name"],
            "district": shop["district"],
            "review_id": review.get("reviewId"),
            "score_overall": score_50,
            "score_stars": stars,
            "title": title,
            "body": body,
            "text": text,
            "text_len": len(text),
            "n_photo": review.get("photoCount"),
            "like_count": review.get("ratingUpCount"),
            "submit_time": (review.get("submitTime") or "")[:10],
        })
    return rows


# ============================================================
# 5. Output
# ============================================================

def write_csv(path, rows, columns):
    if not rows:
        print(f"no rows for {path.name}, skipped")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"saved {path.relative_to(HERE)}  ({len(rows)} rows x {len(columns)} cols)")


def write_combined(shops, reviews):
    shop_by_id = {str(s["poi_id"]): s for s in shops}
    rows = []
    for review in reviews:
        shop = shop_by_id.get(str(review["poi_id"]), {})
        merged = dict(review)
        merged.update({
            "shop_score_overall": shop.get("score_overall"),
            "shop_n_review": shop.get("n_review"),
            "price_band": shop.get("price_band"),
            "price_mid_hkd": shop.get("price_mid_hkd"),
            "street_clean": shop.get("street_clean"),
            "open_year": shop.get("open_year"),
            "years_open": shop.get("years_open"),
            "is_chain_suspect": shop.get("is_chain_suspect"),
            "cuisines": shop.get("cuisines"),
        })
        rows.append(merged)
    write_csv(DATA_DIR / "combined.csv", rows, COMBINED_COLUMNS)


# ============================================================
# 6. Rebuild
# ============================================================

def rebuild_from_cache():
    pages = sorted(RAW_SHOP_DIR.glob("*.json"))
    if not pages:
        print("No cached shop pages in raw/shops/. Run online first.")
        return

    district_by_slug = {d["slug"]: d for d in DISTRICTS}
    shops = []
    seen = set()

    for path in pages:
        slug = path.stem.rsplit("-", 1)[0]
        district = district_by_slug.get(slug)
        if district is None:
            continue
        scraped_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for poi in (payload.get("paginationResult") or {}).get("results", []):
            row = parse_shop(poi, district, scraped_at)
            if row["poi_id"] in seen:
                continue
            seen.add(row["poi_id"])
            shops.append(row)

    detect_chains(shops)
    write_csv(DATA_DIR / "shops.csv", shops, SHOP_COLUMNS)

    shop_by_id = {str(s["poi_id"]): s for s in shops}
    reviews = []
    for path in sorted(RAW_REVIEW_DIR.glob("*.json")):
        shop = shop_by_id.get(path.stem)
        if shop is None:
            continue
        reviews.extend(build_review_rows(shop, json.loads(path.read_text(encoding="utf-8"))))

    write_csv(DATA_DIR / "reviews.csv", reviews, REVIEW_COLUMNS)
    write_combined(shops, reviews)
    print(f"\nRebuilt {len(shops)} shops and {len(reviews)} reviews from cache (no network).")


# ============================================================
# 7. Main
# ============================================================

def print_summary(shops, reviews):
    print("\n" + "=" * 60)
    print(f"shops: {len(shops)}   reviews: {len(reviews)}")
    print(f"{'district':<10}{'shops':>7}{'reviews':>10}")

    for district in DISTRICTS:
        n_shop = sum(1 for s in shops if s["district"] == district["zh"])
        if not n_shop:
            continue
        n_review = sum(1 for r in reviews if r["district"] == district["zh"])
        print(f"{district['zh']:<10}{n_shop:>7}{n_review:>10}")

    listed = sum(int(s["n_review"] or 0) for s in shops)
    if listed:
        print(f"\n  review coverage: {len(reviews):,} / {listed:,} = {len(reviews) / listed:.2%}")
        print("(95%-100% is normal: pending or hidden reviews are not returned)")

    print(f"shops without reviews: {sum(1 for s in shops if not int(s['n_review'] or 0))}")
    print(f"shops without opening date: {sum(1 for s in shops if not s['open_year'])}")
    print(f"suspected chains: {sum(1 for s in shops if s['is_chain_suspect'])}")


def main():
    if OFFLINE_REBUILD:
        rebuild_from_cache()
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_SHOP_DIR.mkdir(parents=True, exist_ok=True)
    RAW_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    if ONLY_DISTRICT:
        districts = [d for d in DISTRICTS if d["zh"] == ONLY_DISTRICT]
        if not districts:
            print(f"Unknown district: {ONLY_DISTRICT}. Choose from {[d['zh'] for d in DISTRICTS]}")
            return
    else:
        districts = DISTRICTS

    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- Step 1: shops ----------
    shops = []
    for district in districts:
        print(f"\n== {district['en']} ({district['zh']})  districtId={district['id']}")
        rows, total = scrape_district(district, scraped_at)
        status = "OK" if len(rows) == total else "MISMATCH"
        print(f"{len(rows)} of {total}  [{status}]")
        shops.extend(rows)

    detect_chains(shops)
    write_csv(DATA_DIR / "shops.csv", shops, SHOP_COLUMNS)

    # ---------- Step 2: reviews ----------
    targets = [s for s in shops if int(s["n_review"] or 0) > 0]
    targets.sort(key=lambda s: -int(s["n_review"] or 0))
    if MAX_SHOPS_FOR_REVIEWS:
        targets = targets[:MAX_SHOPS_FOR_REVIEWS]

    print(f"\n== reviews: {len(targets)} shops")
    reviews = []
    for index, shop in enumerate(targets, 1):
        raw_reviews, from_cache = fetch_reviews(shop)
        rows = build_review_rows(shop, raw_reviews)
        reviews.extend(rows)
        tag = " (cached)" if from_cache else ""
        print(f"[{index}/{len(targets)}] {shop['name'][:28]:<28} {len(rows):>5}/{shop['n_review']}{tag}")

    write_csv(DATA_DIR / "reviews.csv", reviews, REVIEW_COLUMNS)
    write_combined(shops, reviews)
    print_summary(shops, reviews)
    print("\nDone. Files are in data/.")


if __name__ == "__main__":
    main()