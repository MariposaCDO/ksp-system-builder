#!/usr/bin/env python3
"""
download_itemized_specs.py

Downloads and compiles comprehensive PC component specifications 
(CPUs, Motherboards, RAM, GPUs, PSUs) from open-source dataset mirrors.
"""

import json
import logging
import sys
import urllib.request
import urllib.error
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="[SPECS_DB] %(message)s")

from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths

TARGET_SPECS_PATH = CatalogPaths.ITEMIZED_SPECS

# Public open-source dataset raw URLs (60,000+ parts)
DATASET_BASE_URL = "https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/json"
CATEGORIES = {
    "cpus": f"{DATASET_BASE_URL}/cpu.json",
    "motherboards": f"{DATASET_BASE_URL}/motherboard.json",
    "ram": f"{DATASET_BASE_URL}/memory.json",
    "gpus": f"{DATASET_BASE_URL}/video-card.json",
    "psus": f"{DATASET_BASE_URL}/power-supply.json"
}


def download_full_dataset() -> dict:
    compiled_db = {}

    for cat_name, url in CATEGORIES.items():
        logging.info(f"Fetching full spec list for [{cat_name.upper()}] from remote dataset...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KspAgent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    compiled_db[cat_name] = raw_data
                    logging.info(f" -> Loaded {len(raw_data)} items for {cat_name}.")
        except Exception as e:
            logging.warning(f"Failed to fetch {cat_name} ({e}). Inserting empty container.")
            compiled_db[cat_name] = []

    return compiled_db


def main():
    db = download_full_dataset()
    
    # Save formatted JSON to local disk
    with open(TARGET_SPECS_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    total_items = sum(len(items) for items in db.values())
    line_count = len(TARGET_SPECS_PATH.read_text(encoding="utf-8").splitlines())
    
    logging.info("=" * 60)
    logging.info(f"[SUCCESS] Saved {TARGET_SPECS_PATH.name}")
    logging.info(f"Total Components Indexed: {total_items:,}")
    logging.info(f"File Line Count: {line_count:,} lines")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()