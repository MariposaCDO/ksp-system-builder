import json
import re
import requests
import os
from typing import Optional
from ksp_pc_builder_agent_bundle import KspPcBuilderAgentEngine
from ollama.self_healer import OllamaSelfHealer

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/chat" if not OLLAMA_BASE_URL.endswith("/api/chat") else OLLAMA_BASE_URL
MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

AGENT_SYSTEM_PROMPT = """
role: system
task: Validate and generate PC build configurations from the provided JSON database.

instructions:
  1. HARD COMPATIBILITY RULE (SOCKET MATCHING):
     - The 'socket' attribute of the CPU MUST EXACTLY MATCH the 'socket' attribute of the Motherboard.
     - NEVER pair mismatched sockets (e.g., LGA1851 CPU with LGA1700 or AM5 Motherboard).

  2. DATASET COMPLETENESS CHECK:
     - Check if all essential categories exist in the provided JSON: [CPU, CPU Cooler, Motherboard, RAM, PSU, Storage, Case].
     - If categories are missing from the JSON dataset, clearly state:
       "INCOMPLETE DATASET: The following essential components are missing from the input JSON: [list missing categories]."

  3. THERMAL & TDP MATCHING:
     - Ensure the CPU Cooler's max supported TDP is equal to or greater than the CPU's TDP / Base Power.

  4. OUTPUT FORMAT:
     - Output ONLY verified compatible builds.
     - For each build, explicitly print:
       - CPU model & Socket
       - Motherboard model & Socket
       - Cooler model
       - Socket Compatibility Verification: [MATCH / MISMATCH]
       - System Completeness Status: [COMPLETE / INCOMPLETE]

When the user asks for a PC build:
1. Extract the target games list and budget amount (in ILS).
2. Call the `build_pc` function using structured JSON format.

JSON Tool Call Format:
{
  "thought": "Extracting target games and budget from prompt",
  "tool": "build_pc",
  "args": {
    "games": ["minecraft", "roblox"],
    "budget": 3500.0
  }
}

If the output from `build_pc` is returned, explain the final recommendation clearly and conversationally.
"""

class PcAgentService:
    def __init__(self, auto_heal: Optional[bool] = None):
        self.engine = KspPcBuilderAgentEngine()
        self.healer = OllamaSelfHealer(base_url=OLLAMA_BASE_URL, primary_model=MODEL)
        self.auto_heal = auto_heal if auto_heal is not None else os.getenv("AUTO_HEAL_MODELS", "true").lower() in ("true", "1")
        self.active_model = MODEL

    def ensure_llm_ready(self) -> bool:
        """Verify model availability or auto-heal it."""
        if self.auto_heal:
            ok, model_or_err = self.healer.heal_model_dependencies(auto_pull=True)
            if ok:
                self.active_model = model_or_err
                return True
            return False
        return self.healer.is_model_installed(self.active_model)

    def process_prompt(self, user_prompt: str) -> dict:
        games = []
        budget = 3500.0

        try:
            self.ensure_llm_ready()
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": self.active_model,
                    "messages": [
                        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0},
                },
                timeout=90,
            ).json()

            content = json.loads(response["message"]["content"])
            args = content.get("args", {})
            games = args.get("games", games)
            budget = float(args.get("budget", budget))

        except Exception:
            # Deterministic regex extraction fallback
            budget_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ils|nis|₪|budget)", user_prompt, re.I) or re.search(r"under\s*(\d+(?:\.\d+)?)", user_prompt, re.I)
            if budget_match:
                budget = float(budget_match.group(1))

            clean_p = re.sub(r"build.*(?:for|to play)|under.*|budget.*|\d+\s*ils", "", user_prompt, flags=re.I).strip()
            game_matches = re.findall(r"([a-zA-Z0-9\s:-]{3,})", clean_p)
            for g in game_matches:
                g_str = g.strip()
                if g_str and g_str.lower() not in ["i want", "pc", "a", "for", "with"]:
                    games.append(g_str.lower())
            
            if not games:
                games = ["sims 4"]

        return self.engine.process_build_request_tiered(games=games, max_budget=budget)

    def process_explicit(self, games: list, budget: float) -> dict:
        return self.engine.process_build_request_tiered(games=games, max_budget=budget)

    def get_all_games(self) -> dict:
        return self.engine.game_rules._catalog

    def upsert_game(self, game: str, required_ram_gb: int, required_vram_gb: int, source_url: Optional[str] = None) -> dict:
        return self.engine.game_rules.upsert_game(game, required_ram_gb, required_vram_gb, source_url)

    def add_game(self, game: str, required_ram_gb: int, required_vram_gb: int, source_url: Optional[str] = None) -> dict:
        return self.engine.game_rules.add_game(game, required_ram_gb, required_vram_gb, source_url)

    def update_game(self, game: str, required_ram_gb: int, required_vram_gb: int, source_url: Optional[str] = None) -> dict:
        return self.engine.game_rules.update_game(game, required_ram_gb, required_vram_gb, source_url)

    def get_components_by_category(self, category: str, max_price: Optional[float] = None) -> list:
        return self.engine.catalog.get_category(category, max_price=max_price)
