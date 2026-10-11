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
        requirements.  Unknown games are listed in ``unrecognized_games``;
        no automatic remote fetching is performed.
        """
        aggregated: Dict[str, Any] = {
            "required_ram_gb":    8,
            "required_vram_gb":   2,
            "detected_games":     [],
            "unrecognized_games": [],
        }

        for entry in game_inputs:
            clean_key = entry.strip().lower()
            matched   = self._find_in_catalog(clean_key)

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
                    " -> WARNING: '%s' not in catalog. Run the games pipeline offline to add it.",
                    entry,
                )
                aggregated["unrecognized_games"].append(entry)

        return aggregated

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_in_catalog(self, clean_key: str) -> Optional[Dict[str, Any]]:
        for key, data in self._catalog.items():
            if key == clean_key or key in clean_key or clean_key in key:
                return data
        return None