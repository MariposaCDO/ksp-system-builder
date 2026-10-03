"""Path constants for runtime catalog JSON and pipeline outputs."""
from pathlib import Path

_BUNDLE_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _BUNDLE_ROOT / "data"
CATALOGS_DIR = DATA_DIR / "catalogs"


class CatalogPaths:
    PARTS_DB = CATALOGS_DIR / "parts" / "parts_db.json"
    GAME_REQUIREMENTS = CATALOGS_DIR / "games" / "game_requirements.json"
    KNOWN_GAMES_URLS = CATALOGS_DIR / "games" / "known_games_url.json"
    ITEMIZED_SPECS = CATALOGS_DIR / "compatibility" / "itemized_parts_specs.json"
    COMPATIBILITY_DB = CATALOGS_DIR / "compatibility" / "compatibility_db.json"
