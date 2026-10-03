#!/usr/bin/env python3
"""
KSP Game-Aware PC System Builder — CLI Entry Point

Usage examples
--------------
# Natural-language mode (via local Ollama model):
  python main.py --prompt "Build me a PC for Cyberpunk 2077 with 6000 ILS"

# Explicit mode:
  python main.py --games cyberpunk-2077 --budget 6000

# Select a single tier (minimal | best_gpu | best_cpu | budget_60 | budget_80 | budget_100):
  python main.py --games cyberpunk-2077 --budget 6000 --tier best_gpu

# Staleness flags (for automation / CI):
  python main.py --games minecraft --budget 3000 --ignore-stale
  python main.py --games minecraft --budget 3000 --update-stale

Parameters
----------
--prompt / -p       Natural-language request forwarded to Ollama.
--games  / -g       Explicit list of game names (space-separated).
--budget / -b       Budget in ILS.
--tier              Display only one specific tier. Omit to show all tiers.
--update-stale      Automatically trigger update pipelines for any DB file
                    older than 30 days (no interactive prompt).
--ignore-stale      Skip staleness prompts silently. A warning is still printed
                    at the end of the run regardless of this flag.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
CLI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CLI_DIR.parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ksp_pc_builder_agent_bundle import KspPcBuilderAgentEngine, run_preflight_checks
from ksp_pc_builder_agent_bundle.ksp_pc_builder_agent_engine import TIER_LABELS

# ---------------------------------------------------------------------------
# Ollama config
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

AGENT_SYSTEM_PROMPT = """
You are an expert PC Building Assistant for KSP Hardware.
Your role is to converse naturally with the user, understand their target games and budget, and trigger the `build_pc` tool.

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_TIERS = {"minimal", "best_gpu", "best_cpu", "budget_60", "budget_80", "budget_100"}
STALE_THRESHOLD_DAYS = 30


def clean_bidi_text(text: str) -> str:
    """Removes RTL characters for aligned ASCII table rendering."""
    if not text:
        return ""
    english_only = re.sub(r'[\u0590-\u05FF]', '', text)
    return re.sub(r'\s+', ' ', english_only).strip(" -'\"")


def _stale_mode_from_args(args: argparse.Namespace) -> str:
    """Resolve stale_mode string from parsed CLI args."""
    if getattr(args, "update_stale", False):
        return "update"
    if getattr(args, "ignore_stale", False):
        return "ignore"
    return "ask"


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _display_build_tier(tier_key: str, tier: dict) -> None:
    """Render a single build tier as an ASCII table."""
    label = TIER_LABELS.get(tier_key, tier_key)
    budget = tier.get("budget", 0.0)
    total  = tier.get("total_price", 0.0)
    within = tier.get("within_budget", False)
    missing = tier.get("missing_categories", [])

    print("\n" + "=" * 80)
    print(f"  TIER: {label}")
    print(f"  Tier Budget : {budget:.2f} ILS")
    print(f"  Total Cost  : {total:.2f} ILS  {'[OK within budget]' if within else '[OVER BUDGET]'}")
    if missing:
        print(f"  [MISSING]   : {', '.join(missing)}")
    print("-" * 80)
    print(f"{'CATEGORY':<12} | {'PRICE (ILS)':<11} | {'PART NAME'}")
    print("-" * 80)

    for cat, part in tier.get("build", {}).items():
        cat_str   = cat.upper()
        price_str = f"{part.get('price', 0.0):.2f}"
        name      = clean_bidi_text(part.get("name", ""))
        print(f"{cat_str:<12} | {price_str:<11} | {name}")

    print("=" * 80)


def _display_all_tiers(result: dict, filter_tier: str = None) -> None:
    """Render all (or one filtered) tier(s) from a tiered result."""
    print("\n" + "=" * 80)
    print(f"  KSP PC Build -- Games: {result.get('requested_games', [])}")
    print(f"  Max Budget   : {result.get('target_budget', 0.0):.2f} ILS")
    print("=" * 80)

    tiers = result.get("tiers", {})

    if filter_tier:
        if filter_tier not in tiers:
            print(f"[ERROR] Tier '{filter_tier}' not available. Available: {list(tiers.keys())}")
            return
        _display_build_tier(filter_tier, tiers[filter_tier])
    else:
        # Display in logical order
        display_order = [
            "minimal", "best_gpu", "best_cpu",
            "budget_60", "budget_80", "budget_100",
        ]
        for key in display_order:
            if key in tiers:
                _display_build_tier(key, tiers[key])

    # Warnings (budget too low, missing categories, etc.)
    for w in result.get("warnings", []):
        print(f"\n[WARNING] {w}")


def _display_stale_warning(stale_files: list) -> None:
    """Always shown at the end of a run if any DB file is stale, regardless of --ignore-stale."""
    if not stale_files:
        return
    print("\n" + "=" * 80)
    print(f"[DATA FRESHNESS WARNING]")
    print(f"The following database files are older than {STALE_THRESHOLD_DAYS} days:")
    for f in stale_files:
        print(f"  * {f}")
    print("Re-run with --update-stale to refresh, or run the relevant pipeline scripts manually.")
    print("=" * 80)


# ---------------------------------------------------------------------------
# Ollama agent
# ---------------------------------------------------------------------------

class OllamaCliAgent:
    def __init__(self, engine: KspPcBuilderAgentEngine):
        self.engine = engine

    def execute_prompt(self, user_prompt: str, tier_filter: str = None) -> dict:
        print(f"\n[AGENT] Interpreting user prompt with Ollama ({MODEL})...")

        games  = []
        budget = 3500.0

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0},
                },
                timeout=5,
            ).json()

            content = json.loads(response["message"]["content"])
            args    = content.get("args", {})
            games   = args.get("games", games)
            budget  = float(args.get("budget", budget))

        except Exception as e:
            # Deterministic regex extraction from prompt on Ollama failure
            print(f"[FALLBACK] Ollama offline ({e}). Using deterministic extraction from prompt...")
            budget_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ils|nis|₪|budget)", user_prompt, re.I) or re.search(r"under\s*(\d+(?:\.\d+)?)", user_prompt, re.I)
            if budget_match:
                budget = float(budget_match.group(1))

            # Extract game candidates (e.g. "Sims 4", "Minecraft", "Cyberpunk 2077")
            clean_p = re.sub(r"build.*(?:for|to play)|under.*|budget.*|\d+\s*ils", "", user_prompt, flags=re.I).strip()
            # Look for common game phrases
            game_matches = re.findall(r"([a-zA-Z0-9\s:-]{3,})", clean_p)
            for g in game_matches:
                g_str = g.strip()
                if g_str and g_str.lower() not in ["i want", "pc", "a", "for", "with"]:
                    games.append(g_str.lower())
            
            if not games:
                games = ["sims 4"]

        print(f"[ENGINE] Running tiered build for {games} @ {budget} ILS...")
        result = self.engine.process_build_request_tiered(games=games, max_budget=budget)
        _display_all_tiers(result, filter_tier=tier_filter)
        return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="KSP Game-Aware System Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--prompt",   "-p", type=str,   help="Natural language request for Ollama")
    parser.add_argument("--games",    "-g", nargs="+",  help="Explicit games list")
    parser.add_argument("--budget",   "-b", type=float, help="Explicit budget in ILS")
    parser.add_argument(
        "--tier",
        choices=sorted(VALID_TIERS),
        default=None,
        help="Display only one specific build tier (default: all tiers)",
    )
    parser.add_argument(
        "--update-stale",
        action="store_true",
        help=(
            "Automatically trigger update pipelines for any DB file older than "
            f"{STALE_THRESHOLD_DAYS} days. No interactive prompt."
        ),
    )
    parser.add_argument(
        "--ignore-stale",
        action="store_true",
        help=(
            "Skip staleness prompts and continue with existing DB files. "
            "A stale warning is still printed at the end of the run."
        ),
    )
    args = parser.parse_args()

    stale_mode = _stale_mode_from_args(args)

    # Pre-flight checks — returns (ok, stale_files)
    ok, stale_files = run_preflight_checks(stale_mode=stale_mode)
    if not ok:
        sys.exit(1)

    engine    = KspPcBuilderAgentEngine()
    cli_agent = OllamaCliAgent(engine)

    if args.prompt:
        result = cli_agent.execute_prompt(args.prompt, tier_filter=args.tier)
    elif args.games or args.budget:
        games  = args.games  or ["minecraft", "roblox"]
        budget = args.budget or 3500.0
        print(f"[ENGINE] Running tiered build for {games} @ {budget} ILS...")
        result = engine.process_build_request_tiered(games=games, max_budget=budget)
        _display_all_tiers(result, filter_tier=args.tier)
    else:
        # Default demo prompt
        result = cli_agent.execute_prompt(
            "Build me a PC for Minecraft and Roblox with a budget of 3500 ILS",
            tier_filter=args.tier,
        )

    # Always surface stale warning at end of run regardless of --ignore-stale
    _display_stale_warning(stale_files)


if __name__ == "__main__":
    main()