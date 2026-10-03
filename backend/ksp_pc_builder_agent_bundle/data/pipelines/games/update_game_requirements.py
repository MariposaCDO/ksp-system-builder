import argparse
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.io import load_json, save_json
from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths

GAMES_DB_PATH = CatalogPaths.GAME_REQUIREMENTS
KNOWN_URLS_PATH = CatalogPaths.KNOWN_GAMES_URLS


def parse_game_specs_from_url(url: str) -> dict:
    """Mock parser/scraper interface for game requirement URLs."""
    print(f"[SCRAPER] Fetching and parsing HTML from {url}...")
    return {
        "required_ram_gb": 16,
        "required_vram_gb": 4
    }


def update_single_game(game_name: str, url: str) -> bool:
    game_key = game_name.lower().strip()
    games_db = load_json(GAMES_DB_PATH, {"last_updated": "", "games": {}})
    now = datetime.now(timezone.utc)

    existing_entry = games_db.get("games", {}).get(game_key)
    if existing_entry and "last_updated" in existing_entry:
        last_updated = datetime.fromisoformat(existing_entry["last_updated"])
        if now - last_updated < timedelta(days=1):
            print(
                f"[CACHE] Game '{game_key}' updated in the last 24 hours "
                f"({existing_entry['last_updated']}). Skipping fetch."
            )
            return False

    parsed_specs = parse_game_specs_from_url(url)

    game_data = {
        "game": game_key,
        "required_ram_gb": parsed_specs["required_ram_gb"],
        "required_vram_gb": parsed_specs["required_vram_gb"],
        "source_url": url,
        "last_updated": now.isoformat()
    }
    games_db["games"][game_key] = game_data
    games_db["last_updated"] = now.isoformat()

    save_json(GAMES_DB_PATH, games_db)
    print(f"[SUCCESS] Updated '{game_key}' in {GAMES_DB_PATH.name}")

    known_urls = load_json(KNOWN_URLS_PATH, [])
    url_exists = any(item.get("game") == game_key for item in known_urls)
    if not url_exists:
        known_urls.append({"game": game_key, "url": url})
        save_json(KNOWN_URLS_PATH, known_urls)
        print(f"[SUCCESS] Appended '{game_key}' to {KNOWN_URLS_PATH.name}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update single game requirement entry.")
    parser.add_argument("--game", required=True, help="Game title slug")
    parser.add_argument("--url", required=True, help="Game requirement URL")
    args = parser.parse_args()

    update_single_game(args.game, args.url)
