import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.io import load_json, save_json
from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths
from ksp_pc_builder_agent_bundle.data.pipelines.games.srl_client import (
    resolve_best_srl_game,
    fetch_srl_game_specs,
    parse_specs_from_srl_html,
)

GAMES_DB_PATH = CatalogPaths.GAME_REQUIREMENTS


def parse_game_specs_from_url(url: str) -> dict:
    """Scraper interface for game requirement URLs."""
    print(f"[SCRAPER] Fetching and parsing HTML from {url}...")
    return fetch_srl_game_specs(url)


def update_single_game(
    game_name: str,
    url: Optional[str] = None,
    force: bool = False,
) -> bool:
    """
    Ensure game requirements are available in game_requirements.json.
    
    1. If the game is already in game_requirements.json:
       - Checks staleness / cache. If updated within 24h (or force=False when cached),
         uses the existing entry without re-resolving or re-fetching.
    2. If missing or update required:
       - Resolves URL via SRL search API (handler=searchterm) if url is not explicitly provided.
       - Fetches specs and stores them directly into game_requirements.json.
    """
    game_key = game_name.lower().strip()
    games_db = load_json(GAMES_DB_PATH, {"last_updated": "", "schema_version": "2.0", "games": {}})
    now = datetime.now(timezone.utc)

    existing_entry = games_db.get("games", {}).get(game_key)
    if existing_entry and not force:
        if "last_updated" in existing_entry:
            try:
                last_updated = datetime.fromisoformat(existing_entry["last_updated"])
                if now - last_updated < timedelta(days=1):
                    print(
                        f"[CACHE] Game '{game_key}' already on file and updated recently "
                        f"({existing_entry['last_updated']}). Using existing entry without re-resolving."
                    )
                    return True
            except Exception:
                pass
        else:
            print(f"[CACHE] Game '{game_key}' already on file. Skipping remote fetch.")
            return True

    # Resolve URL if not supplied
    target_url = url
    display_title = game_name.title()
    if not target_url:
        print(f"[RESOLVER] Searching SRL for game '{game_name}' via searchterm API...")
        match = resolve_best_srl_game(game_name)
        if not match or not match.get("url"):
            if existing_entry and existing_entry.get("source_url"):
                target_url = existing_entry["source_url"]
            else:
                print(f"[RESOLVER ERROR] Could not find SRL match for '{game_name}'.")
                return False
        else:
            target_url = match["url"]
            display_title = match.get("title") or display_title
            print(f" -> Found match: {display_title} ({target_url})")

    parsed_specs = parse_game_specs_from_url(target_url)

    game_data = {
        "game":             game_key,
        "display_name":     display_title,
        "required_ram_gb":  parsed_specs["required_ram_gb"],
        "required_vram_gb": parsed_specs["required_vram_gb"],
        "tiers":            parsed_specs.get("tiers", {}),
        "source_url":       target_url,
        "last_updated":     now.isoformat(),
    }
    games_db["games"][game_key] = game_data
    games_db["last_updated"]   = now.isoformat()
    games_db["schema_version"] = "2.0"

    save_json(GAMES_DB_PATH, games_db)
    print(f"[SUCCESS] Updated '{game_key}' in {GAMES_DB_PATH.name}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update single game requirement entry.")
    parser.add_argument("--game", required=True, help="Game title slug")
    parser.add_argument("--url", default=None, help="Game requirement URL (optional)")
    parser.add_argument("--force", action="store_true", help="Force update even if cached")
    args = parser.parse_args()

    update_single_game(args.game, url=args.url, force=args.force)
