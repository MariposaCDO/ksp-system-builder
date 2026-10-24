import json
from datetime import datetime, timezone
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths
from ksp_pc_builder_agent_bundle.data.common.io import load_json, save_json
from ksp_pc_builder_agent_bundle.data.pipelines.games.update_game_requirements import (
    parse_game_specs_from_url,
)

GAMES_DB_PATH = CatalogPaths.GAME_REQUIREMENTS


def download_game_requirements_catalog() -> None:
    """
    Refresh game_requirements.json entries directly using their existing source_url.
    Does not require known_games_url.json.
    """
    if not GAMES_DB_PATH.exists():
        print(f"[ERROR] {GAMES_DB_PATH.name} not found.")
        return

    catalog = load_json(GAMES_DB_PATH, {"last_updated": "", "schema_version": "2.0", "games": {}})
    games_map = catalog.get("games", {})

    now = datetime.now(timezone.utc).isoformat()
    catalog["last_updated"] = now
    catalog["schema_version"] = "2.0"

    print(f"[DOWNLOAD] Refreshing {len(games_map)} games in game requirements catalog...")

    for game_key, entry in games_map.items():
        url = entry.get("source_url")
        if not url:
            print(f"[SKIP] No source_url for '{game_key}', skipping.")
            continue

        try:
            parsed_specs = parse_game_specs_from_url(url)
            entry["required_ram_gb"] = parsed_specs["required_ram_gb"]
            entry["required_vram_gb"] = parsed_specs["required_vram_gb"]
            entry["tiers"] = parsed_specs.get("tiers", {})
            entry["last_updated"] = now
            print(f" -> Updated {game_key} successfully.")
        except Exception as e:
            print(f"[WARN] Failed to refresh '{game_key}' from {url}: {e}")

    save_json(GAMES_DB_PATH, catalog)
    print(f"[SUCCESS] Refreshed {GAMES_DB_PATH.name} ({len(games_map)} games).")


def run() -> None:
    download_game_requirements_catalog()


if __name__ == "__main__":
    download_game_requirements_catalog()
