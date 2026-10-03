import os
from pathlib import Path
from typing import Union

from .data.common.paths import CATALOGS_DIR, CatalogPaths


class Config:
    """Dynamic path resolution and configuration defaults for the agent bundle."""

    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"
    CATALOGS_DIR = CATALOGS_DIR

    PARTS_DB_PATH = Path(
        os.getenv("KSP_PARTS_DB_PATH", CatalogPaths.PARTS_DB)
    )
    GAME_REQUIREMENTS_PATH = CatalogPaths.GAME_REQUIREMENTS
    ITEMIZED_SPECS_PATH = CatalogPaths.ITEMIZED_SPECS
    COMPATIBILITY_DB_PATH = CatalogPaths.COMPATIBILITY_DB
    KNOWN_GAMES_URLS_PATH = CatalogPaths.KNOWN_GAMES_URLS

    DEFAULT_CURRENCY = "ILS"
    MAX_RECOMMENDATIONS = 5

    @classmethod
    def resolve_parts_db(cls, db_path: Union[str, Path, None] = None) -> Path:
        """Return resolved path to the parts_db.json catalog."""
        target = Path(db_path) if db_path else Path(cls.PARTS_DB_PATH)
        if not target.exists():
            raise FileNotFoundError(f"Parts catalog database not found at: {target}")
        return target
