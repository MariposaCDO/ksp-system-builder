"""
Game Requirements Rules — static catalog reader.

Reads hardware requirements from the pre-built local game_requirements.json
catalog ONLY.  No live HTTP fetches occur at runtime — all remote data ingestion
is handled exclusively by the offline pipeline scripts in data/pipelines/games/.

If a game is not found in the catalog, it is surfaced as an unrecognized entry
and the caller is responsible for triggering the appropriate pipeline offline.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from ksp_pc_builder_agent_bundle.ksp_pc_builder_config import Config

logger = logging.getLogger("KspAgentEngine")

GAMES_DB_PATH: Path = Config.GAME_REQUIREMENTS_PATH


import re

def normalize_game_title(title: str) -> str:
    """
    Normalize game title:
    - Lowercase and strip whitespace
    - Replace dashes, underscores, colons with spaces (e.g. 'cyberpunk-2077' -> 'cyberpunk 2077')
    - Separate letters and digits (e.g. 'sim6' -> 'sim 6', 'sims4' -> 'sims 4')
    - Collapse multiple spaces
    """
    if not title:
        return ""
    cleaned = title.strip().lower()
    cleaned = re.sub(r'[\-_:\.]+', ' ', cleaned)
    cleaned = re.sub(r'([a-zA-Z]+)(\d+)', r'\1 \2', cleaned)
    cleaned = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


class GameRequirementsRules:
    """Evaluates PC build requirements against locally-cached game hardware specs."""

    def __init__(self, db_path: Path = GAMES_DB_PATH):
        self.db_path = db_path
        self._catalog: Dict[str, Any] = self._load_catalog()

    # ------------------------------------------------------------------
    # Catalog I/O
    # ------------------------------------------------------------------

    def _load_catalog(self) -> Dict[str, Any]:
        """Load and return the games dictionary from the local JSON catalog."""
        if self.db_path.exists():
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f).get("games", {})
        logger.warning("[GameRequirementsRules] Catalog not found at %s", self.db_path)
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_requirements(self, game_inputs: List[str]) -> Dict[str, Any]:
        """
        Look up each game in the local catalog and aggregate minimum hardware
        requirements.  Unknown games are listed in ``unrecognized_games`` with their
        normalized search representation; no automatic remote fetching is performed.
        """
        aggregated: Dict[str, Any] = {
            "required_ram_gb":    8,
            "required_vram_gb":   2,
            "detected_games":     [],
            "unrecognized_games": [],
        }

        for entry in game_inputs:
            normalized_key = normalize_game_title(entry)
            if not normalized_key:
                continue

            matched = self._find_in_catalog(normalized_key)

            if matched:
                logger.info(" -> Game Recognized: %s", matched["game"])
                aggregated["detected_games"].append(matched["game"])
                aggregated["required_ram_gb"]  = max(
                    aggregated["required_ram_gb"],  matched.get("required_ram_gb",  8)
                )
                aggregated["required_vram_gb"] = max(
                    aggregated["required_vram_gb"], matched.get("required_vram_gb", 2)
                )
            else:
                logger.warning(
                    " -> WARNING: '%s' (searched as '%s') not in catalog. Run the games pipeline offline or add it via API.",
                    entry,
                    normalized_key,
                )
                aggregated["unrecognized_games"].append(normalized_key)

        return aggregated


    def reload(self) -> None:
        """Reload the catalog from disk."""
        self._catalog = self._load_catalog()

    def upsert_game(self, game_name: str, required_ram_gb: int, required_vram_gb: int, source_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Canonical upsert mechanism: creates or updates game requirements in memory and persists to disk.
        """
        from datetime import datetime, timezone
        from ksp_pc_builder_agent_bundle.data.common.io import load_json, save_json

        clean_key = game_name.strip().lower()
        now_str = datetime.now(timezone.utc).isoformat()
        
        entry = {
            "game": clean_key,
            "required_ram_gb": int(required_ram_gb),
            "required_vram_gb": int(required_vram_gb),
            "source_url": source_url or "",
            "last_updated": now_str,
        }

        # Update in-memory
        self._catalog[clean_key] = entry

        # Persist to JSON
        raw_db = load_json(self.db_path, {"last_updated": "", "games": {}})
        if "games" not in raw_db:
            raw_db["games"] = {}
        raw_db["games"][clean_key] = entry
        raw_db["last_updated"] = now_str
        save_json(self.db_path, raw_db)

        return entry

    def add_game(self, game_name: str, required_ram_gb: int, required_vram_gb: int, source_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Wrapper that fails if the game is already in the database.
        """
        clean_key = game_name.strip().lower()
        if self._find_in_catalog(clean_key) is not None:
            raise ValueError(f"Game '{clean_key}' already exists in catalog. Use update or upsert.")
        return self.upsert_game(clean_key, required_ram_gb, required_vram_gb, source_url)

    def update_game(self, game_name: str, required_ram_gb: int, required_vram_gb: int, source_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Wrapper that fails if the game is missing from the database.
        """
        clean_key = game_name.strip().lower()
        if self._find_in_catalog(clean_key) is None:
            raise KeyError(f"Game '{clean_key}' not found in catalog. Use add or upsert.")
        return self.upsert_game(clean_key, required_ram_gb, required_vram_gb, source_url)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_in_catalog(self, clean_key: str) -> Optional[Dict[str, Any]]:
        target_norm = normalize_game_title(clean_key)
        for key, data in self._catalog.items():
            if normalize_game_title(key) == target_norm:
                return data
        return None