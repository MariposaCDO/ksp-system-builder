"""
Game URL update pipeline using SystemRequirementsLab searchterm endpoint.

Resolves SRL requirement page URLs for games directly via:
  https://www.systemrequirementslab.com/cyri/?handler=searchterm&term={game_name}

Maintained for compatibility with existing CLI / pipeline invocation commands,
directly operating on or reading from game_requirements.json.
"""

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.io import load_json, save_json
from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths
from ksp_pc_builder_agent_bundle.data.pipelines.games.srl_client import resolve_best_srl_game

GAMES_DB_PATH = CatalogPaths.GAME_REQUIREMENTS


def update_known_games_urls() -> None:
    """
    Ensure all games in game_requirements.json have a valid SRL source_url.
    Any missing URL is resolved using the SRL search API.
    """
    catalog = load_json(GAMES_DB_PATH, {"last_updated": "", "schema_version": "2.0", "games": {}})
    games_map = catalog.get("games", {})

    updated = False
    for game_key, entry in games_map.items():
        current_url = entry.get("source_url", "")
        if not current_url or "systemrequirementslab.com" not in current_url:
            print(f"[RESOLVER] Resolving URL for '{game_key}' via SRL search API...")
            match = resolve_best_srl_game(game_key)
            if match and match.get("url"):
                entry["source_url"] = match["url"]
                print(f" -> Found: {match['url']}")
                updated = True
            else:
                print(f" -> Could not resolve URL for '{game_key}'")

    if updated:
        save_json(GAMES_DB_PATH, catalog)
        print(f"[SUCCESS] Updated URLs in {GAMES_DB_PATH.name}")
    else:
        print("[INFO] All games in catalog already have valid source URLs.")


def run() -> None:
    update_known_games_urls()


if __name__ == "__main__":
    update_known_games_urls()
