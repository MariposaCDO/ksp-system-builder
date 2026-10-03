#!/usr/bin/env python3
"""
download_compatibility_db.py

Downloads or builds a deterministic compatibility database (compatibility_db.json)
containing hardware specifications (sockets, RAM types, form factors, TDP)
independently of catalog price scraping.
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

# Set up clean logging
logging.basicConfig(
    level=logging.INFO,
    format="[COMPAT_DB] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths  # noqa: E402

TARGET_DB_PATH = CatalogPaths.COMPATIBILITY_DB

# Public mirror for hardware spec metadata
REMOTE_DB_URL = "https://raw.githubusercontent.com/datasets/pc-specifications/main/compatibility_rules.json"


def generate_fallback_schema() -> dict:
    """
    Generates a starter, fully-featured deterministic compatibility schema
    covering major platform generations (AM4, AM5, LGA1700, LGA1851, DDR4, DDR5).
    """
    return {
        "version": "1.0.0",
        "sockets": {
            "AM4": {"ram_support": ["DDR4"], "form_factors": ["ATX", "Micro-ATX", "Mini-ITX"]},
            "AM5": {"ram_support": ["DDR5"], "form_factors": ["ATX", "Micro-ATX", "Mini-ITX"]},
            "LGA1700": {"ram_support": ["DDR4", "DDR5"], "form_factors": ["ATX", "Micro-ATX", "Mini-ITX"]},
            "LGA1851": {"ram_support": ["DDR5"], "form_factors": ["ATX", "Micro-ATX", "Mini-ITX"]}
        },
        "form_factors": {
            "ATX": {"compatible_cases": ["ATX", "E-ATX"]},
            "Micro-ATX": {"compatible_cases": ["Micro-ATX", "ATX", "E-ATX"]},
            "Mini-ITX": {"compatible_cases": ["Mini-ITX", "Micro-ATX", "ATX", "E-ATX"]}
        },
        "gpu_exclusions": [
            "holder", "bracket", "support", "cable", "riser", "backplate", "stand", "anti-sag"
        ],
        "gpu_valid_indicators": [
            "rtx", "gtx", "rx", "radeon", "geforce", "arc", "graphics card"
        ],
        "psu_headroom_multiplier": 1.25
    }


def download_or_create_compatibility_db() -> bool:
    """Downloads remote spec rules or writes the starter schema locally."""
    logging.info(f"Target location: {TARGET_DB_PATH}")
    
    data = None
    
    # 1. Try downloading from remote repository
    try:
        logging.info("Attempting to fetch remote compatibility database...")
        req = urllib.request.Request(
            REMOTE_DB_URL, 
            headers={"User-Agent": "KspPcBuilder/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                raw_bytes = response.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                logging.info("Successfully fetched remote compatibility dataset.")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        logging.warning(f"Could not download remote database ({e}). Falling back to local schema creation.")

    # 2. Fall back to local schema generation if remote fetch failed or was empty
    if not data:
        logging.info("Generating deterministic base compatibility schema...")
        data = generate_fallback_schema()

    # 3. Write deterministically to local JSON file
    try:
        with open(TARGET_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logging.info(f"[SUCCESS] Successfully saved {TARGET_DB_PATH.name} ({TARGET_DB_PATH.stat().st_size} bytes).")
        return True
    except Exception as e:
        logging.error(f"Failed to write compatibility database to disk: {e}")
        return False


if __name__ == "__main__":
    success = download_or_create_compatibility_db()
    sys.exit(0 if success else 1)