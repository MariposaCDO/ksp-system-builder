import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from ksp_pc_builder_agent_bundle.data.pipelines.games.update_game_requirements import (
    update_single_game,
)
from ksp_pc_builder_agent_bundle.ksp_pc_builder_config import Config

logger = logging.getLogger("KspAgentEngine")
GAMES_DB_PATH = Config.GAME_REQUIREMENTS_PATH


class GameRequirementsRules:
    """Evaluates PC build requirements against game hardware specs."""

    def __init__(self, db_path: Path = GAMES_DB_PATH):
        self.db_path = db_path
        self._catalog = self._load_catalog()

    def _load_catalog(self) -> Dict[str, Any]:
        if self.db_path.exists():
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f).get("games", {})
        return {}

    def resolve_requirements(self, game_inputs: List[str]) -> Dict[str, Any]:
        aggregated = {
            "required_ram_gb": 8,
            "required_vram_gb": 2,
            "detected_games": [],
            "unrecognized_games": [],
            "auto_fetched_games": []
        }

        # Reload DB to capture recently scraped additions
        self._catalog = self._load_catalog()

        for entry in game_inputs:
            clean_key = entry.strip().lower()

            matched_game = self._find_in_catalog(clean_key)

            # Auto-Fetch Trigger if unknown
            if not matched_game:
                logger.info(f" -> Game '{entry}' not in catalog. Triggering dynamic fetch...")
                # Construct target SRL URL
                srl_url = f"https://www.systemrequirementslab.com/cyri/requirements/{clean_key.replace(' ', '-')}"
                success = update_single_game(clean_key, srl_url)
                
                if success:
                    self._catalog = self._load_catalog()
                    matched_game = self._find_in_catalog(clean_key)
                    if matched_game:
                        aggregated["auto_fetched_games"].append(clean_key)

            if matched_game:
                logger.info(f" -> Game Recognized: {matched_game['game']}")
                aggregated["detected_games"].append(matched_game["game"])
                aggregated["required_ram_gb"] = max(aggregated["required_ram_gb"], matched_game.get("required_ram_gb", 8))
                aggregated["required_vram_gb"] = max(aggregated["required_vram_gb"], matched_game.get("required_vram_gb", 2))
            else:
                logger.warning(f" -> WARNING: Could not resolve specs for '{entry}'. Prompting user for direct URL.")
                aggregated["unrecognized_games"].append(entry)

        return aggregated

    def _find_in_catalog(self, clean_key: str) -> Dict[str, Any] | None:
        for key, data in self._catalog.items():
            if key == clean_key or key in clean_key or clean_key in key:
                return data
        return None