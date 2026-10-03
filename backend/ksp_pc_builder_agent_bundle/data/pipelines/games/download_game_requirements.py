import json
from datetime import datetime, timezone

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths
from ksp_pc_builder_agent_bundle.data.pipelines.games.update_game_requirements import (
    parse_game_specs_from_url,
)

GAMES_DB_PATH = CatalogPaths.GAME_REQUIREMENTS
KNOWN_URLS_PATH = CatalogPaths.KNOWN_GAMES_URLS


def download_game_requirements_catalog() -> None:
    """Replace game_requirements.json from known_games_url.json (full rebuild)."""
    if not KNOWN_URLS_PATH.exists():
        print(f"[ERROR] {KNOWN_URLS_PATH.name} not found.")
        return

    with open(KNOWN_URLS_PATH, "r", encoding="utf-8") as f:
        known_urls = json.load(f)

    now = datetime.now(timezone.utc).isoformat()
    new_catalog = {
        "last_updated": now,
        "games": {}
    }

    print(f"[DOWNLOAD] Rebuilding game requirements from {len(known_urls)} URLs...")

    for entry in known_urls:
        game_key = entry["game"].lower().strip()
        url = entry["url"]

        parsed_specs = parse_game_specs_from_url(url)
        new_catalog["games"][game_key] = {
            "game": game_key,
            "required_ram_gb": parsed_specs["required_ram_gb"],
            "required_vram_gb": parsed_specs["required_vram_gb"],
            "source_url": url,
            "last_updated": now
        }

    with open(GAMES_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(new_catalog, f, indent=2, ensure_ascii=False)

    print(
        f"[SUCCESS] Replaced {GAMES_DB_PATH.name} with "
        f"{len(new_catalog['games'])} games."
    )


if __name__ == "__main__":
    download_game_requirements_catalog()
