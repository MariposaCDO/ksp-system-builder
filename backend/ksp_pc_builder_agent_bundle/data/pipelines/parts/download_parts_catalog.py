#!/usr/bin/env python3
"""
KSP Parts Catalog Downloader
============================
Downloads the PC builder parts catalog from KSP's system builder API and saves
it as a structured JSON database for use by the ksp-system-builder agent.

Fetched endpoints:
  - https://ksp.co.il/m_action/api/comp/16014  (Intel-based system builder)
  - https://ksp.co.il/m_action/api/comp/16015  (AMD-based system builder)

Usage (from agent/ksp-system-builder):
  python backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py
  python .../download_parts_catalog.py --comp-ids 16014 16015 --verbose

Output:
  catalogs/parts/parts_db.json (default) — merged catalog keyed by KSP category name.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    import cloudscraper
except ImportError:
    print("[ERROR] 'cloudscraper' is not installed. Run: pip install cloudscraper")
    sys.exit(1)

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_COMP_IDS = [16014, 16015]
DEFAULT_OUTPUT = CatalogPaths.PARTS_DB

KSP_BASE_URL = "https://ksp.co.il"
COMP_API_URL = KSP_BASE_URL + "/m_action/api/comp/{comp_id}"
ITEM_PAGE_URL = KSP_BASE_URL + "/web/item/{uin}"

# Mapping of KSP category titles (Hebrew) to English slugs used by the agent.
# Categories that appear in multiple system builder configs are de-duplicated.
CATEGORY_TITLE_MAP = {
    "מעבד Intel": "cpu",
    "מעבד אינטל": "cpu",
    "מעבד AMD": "cpu",
    "מעבדים": "cpu",
    "קירור למעבד": "cpu_cooler",
    "לוחות אם למעבדי ‏Intel": "motherboard",
    "לוחות אם למעבדי אינטל": "motherboard",
    "לוחות אם למעבדי ‏AMD": "motherboard",
    "לוחות אם": "motherboard",
    "זכרונות": "ram",
    "כרטיסי מסך": "gpu",
    "כונני SSD": "ssd",
    "דיסקים קשיחים": "hdd",
    "ספקי כוח": "psu",
    "מארזים": "case",
    "מאווררים וגופי קירור": "cooling",
    "צורבי DVD": "optical_drive",
    "כרטיסי קול": "sound_card",
    "ציוד רשתות": "networking",
    "מקלדות": "keyboard",
    "עכברים": "mouse",
    "פד לעכבר": "mousepad",
    "רמקולים": "speakers",
    "אוזניות": "headphones",
    "מסכים": "monitor",
    "כבלים": "cables",
    "מע' הפעלה": "os",
    "אופיס": "office",
    "אנטי וירוסים": "antivirus",
    "מצלמות רשת": "webcam",
    "מדפסת": "printer",
    "הרכבה": "assembly",
    "בקרי משחק": "game_controller",
}

# Retry settings for Cloudflare-protected endpoints
MAX_RETRIES = 5
RETRY_DELAY_SECS = 4.0
INTER_REQUEST_DELAY = 2.5


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def create_session() -> cloudscraper.CloudScraper:
    """Create a cloudscraper session that mimics a real browser."""
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def fetch_comp(session: cloudscraper.CloudScraper, comp_id: int, verbose: bool = False) -> dict:
    """
    Fetch the system builder JSON for a given comp_id.
    Retries up to MAX_RETRIES times on non-200 responses.
    """
    url = COMP_API_URL.format(comp_id=comp_id)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if verbose:
                print(f"  [comp/{comp_id}] Attempt {attempt}/{MAX_RETRIES} -> {url}")
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            else:
                if verbose:
                    print(f"  [comp/{comp_id}] HTTP {resp.status_code}, retrying in {RETRY_DELAY_SECS}s…")
                time.sleep(RETRY_DELAY_SECS)
        except Exception as exc:
            if verbose:
                print(f"  [comp/{comp_id}] Request error: {exc}, retrying in {RETRY_DELAY_SECS}s…")
            time.sleep(RETRY_DELAY_SECS)

    print(f"[WARNING] Could not fetch comp/{comp_id} after {MAX_RETRIES} attempts. Skipping.")
    return {}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def resolve_category_slug(title: str) -> str:
    """Resolve a Hebrew category title to its English slug."""
    return CATEGORY_TITLE_MAP.get(title.strip(), title.strip())


def parse_comp_data(comp_data: dict) -> dict[str, list[dict]]:
    """
    Parse a single comp API response into a dict of:
      { category_slug: [item, ...] }

    Each item is a flat dict with standardized fields:
      uin, name, brand, price, stock, category, category_slug,
      url (product page), ksp_url, tags
    """
    if not comp_data:
        return {}

    parts_meta = comp_data.get("parts", [])
    upgrade_data = comp_data.get("upgrade", {})

    # Build id -> title map from parts metadata
    id_to_title = {p["idnt"]: p["title"] for p in parts_meta}

    result: dict[str, list[dict]] = {}

    for cat_id, cat_content in upgrade_data.items():
        title = id_to_title.get(str(cat_id), cat_id)
        slug = resolve_category_slug(title)
        items_raw = cat_content.get("items", {})

        for uin, item in items_raw.items():
            entry = {
                "uin": item.get("uin", uin),
                "uinsql": item.get("uinsql"),
                "name": item.get("name", ""),
                "brand": item.get("brand", ""),
                "price": _parse_price(item.get("price")),
                "stock": _parse_int(item.get("stock")) or 0,
                "whs_total": _parse_int(item.get("whs_total")),
                "category": title,
                "category_slug": slug,
                "ksp_url": ITEM_PAGE_URL.format(uin=item.get("uinsql", uin)),
                "url": item.get("url") or "",
                "eol": item.get("eol", "0") == "1",
                "dis_payments": _parse_int(item.get("dis_payments")),
                "tags": item.get("tags", {}),
            }
            result.setdefault(slug, [])
            result[slug].append(entry)

    return result


def _parse_price(val) -> float:
    """Parse a price value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _parse_int(val) -> int | None:
    """Parse a value to int, returning None on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def merge_catalogs(catalogs: list[dict[str, list[dict]]]) -> dict[str, list[dict]]:
    """
    Merge multiple category catalogs, de-duplicating by uin.
    """
    merged: dict[str, list[dict]] = {}
    seen_uins: dict[str, set[str]] = {}

    for catalog in catalogs:
        for slug, items in catalog.items():
            merged.setdefault(slug, [])
            seen_uins.setdefault(slug, set())
            for item in items:
                uin = item["uin"]
                if uin not in seen_uins[slug]:
                    merged[slug].append(item)
                    seen_uins[slug].add(uin)

    return merged


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def print_summary(db: dict) -> None:
    """Print a human-readable summary of the downloaded catalog."""
    total = sum(len(v) for v in db.get("categories", {}).values())
    print(f"\n=== Catalog Summary ({db.get('downloaded_at', 'unknown')}) ===")
    print(f"   Sources : {', '.join(str(s) for s in db.get('sources', []))}")
    print(f"   Total items : {total}")
    print()
    for slug, items in sorted(db["categories"].items(), key=lambda x: -len(x[1])):
        in_stock = sum(1 for i in items if i["stock"] > 0)
        avg_price = (sum(i["price"] for i in items if i["price"] > 0)
                     / max(1, sum(1 for i in items if i["price"] > 0)))
        print(f"   {slug:<20} {len(items):>4} items  |  {in_stock:>4} in stock  |  avg ILS{avg_price:>7.0f}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def download_catalog(
    comp_ids: list[int] = DEFAULT_COMP_IDS,
    output: Path = DEFAULT_OUTPUT,
    verbose: bool = False,
) -> dict:
    """
    Download, parse and save the KSP parts catalog.
    Returns the full database dict.
    """
    print(f"[*] Downloading KSP parts catalog from comp IDs: {comp_ids}")
    session = create_session()

    raw_catalogs: list[dict[str, list[dict]]] = []
    for i, comp_id in enumerate(comp_ids):
        if i > 0:
            time.sleep(INTER_REQUEST_DELAY)
        print(f"  Fetching comp/{comp_id}...")
        raw = fetch_comp(session, comp_id, verbose=verbose)
        parsed = parse_comp_data(raw)
        if parsed:
            item_count = sum(len(v) for v in parsed.values())
            print(f"  [OK] comp/{comp_id}: {len(parsed)} categories, {item_count} items")
        else:
            print(f"  [FAIL] comp/{comp_id}: no data returned")
        raw_catalogs.append(parsed)

    print("\n[*] Merging and de-duplicating...")
    merged = merge_catalogs(raw_catalogs)

    db = {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "sources": [COMP_API_URL.format(comp_id=c) for c in comp_ids],
        "categories": merged,
    }

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"[SAVED] {output}")
    print_summary(db)
    return db


def main():
    parser = argparse.ArgumentParser(
        description="Download KSP PC-builder parts catalog to a local JSON database."
    )
    parser.add_argument(
        "--comp-ids",
        nargs="+",
        type=int,
        default=DEFAULT_COMP_IDS,
        metavar="ID",
        help=f"KSP comp IDs to fetch (default: {DEFAULT_COMP_IDS})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed fetch progress",
    )
    args = parser.parse_args()
    download_catalog(comp_ids=args.comp_ids, output=args.output, verbose=args.verbose)


if __name__ == "__main__":
    main()
