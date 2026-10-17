#!/usr/bin/env python3
"""
KSP Game-Aware PC System Builder — CLI Client Entry Point

Usage examples
--------------
  python main.py --prompt "Build me a PC for Cyberpunk 2077 with 6000 ILS"
  python main.py --games cyberpunk-2077 --budget 6000
"""

import argparse
import re
import sys
from pathlib import Path

# Path bootstrap to access backend services directly or switch to requests.post for API
CLI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CLI_DIR.parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.agent_service import PcAgentService
from ksp_pc_builder_agent_bundle import run_preflight_checks
from ksp_pc_builder_agent_bundle.ksp_pc_builder_agent_engine import TIER_LABELS

VALID_TIERS = {"minimal", "best_gpu", "best_cpu", "budget_60", "budget_80", "budget_100"}
STALE_THRESHOLD_DAYS = 30

def clean_bidi_text(text: str) -> str:
    if not text:
        return ""
    english_only = re.sub(r'[\u0590-\u05FF]', '', text)
    return re.sub(r'\s+', ' ', english_only).strip(" -'\"")

def _display_build_tier(tier_key: str, tier: dict) -> None:
    label = TIER_LABELS.get(tier_key, tier_key)
    budget = tier.get("budget", 0.0)
    total = tier.get("total_price", 0.0)
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
        cat_str = cat.upper()
        price_str = f"{part.get('price', 0.0):.2f}"
        name = clean_bidi_text(part.get("name", ""))
        print(f"{cat_str:<12} | {price_str:<11} | {name}")

    print("=" * 80)

def _display_all_tiers(result: dict, filter_tier: str = None) -> None:
    print("\n" + "=" * 80)
    print(f"  KSP PC Build -- Games: {result.get('requested_games', [])}")
    print(f"  Max Budget   : {result.get('target_budget', 0.0):.2f} ILS")
    print("=" * 80)

    tiers = result.get("tiers", {})
    if filter_tier:
        if filter_tier not in tiers:
            print(f"[ERROR] Tier '{filter_tier}' not available.")
            return
        _display_build_tier(filter_tier, tiers[filter_tier])
    else:
        display_order = ["minimal", "best_gpu", "best_cpu", "budget_60", "budget_80", "budget_100"]
        for key in display_order:
            if key in tiers:
                _display_build_tier(key, tiers[key])

    for w in result.get("warnings", []):
        print(f"\n[WARNING] {w}")

def _display_stale_warning(stale_files: list) -> None:
    if not stale_files:
        return
    print("\n" + "=" * 80)
    print(f"[DATA FRESHNESS WARNING]")
    print(f"The following database files are older than {STALE_THRESHOLD_DAYS} days:")
    for f in stale_files:
        print(f"  * {f}")
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(description="KSP Game-Aware System Builder CLI")
    parser.add_argument("--prompt", "-p", type=str, help="Natural language request")
    parser.add_argument("--games", "-g", nargs="+", help="Explicit games list")
    parser.add_argument("--budget", "-b", type=float, help="Explicit budget in ILS")
    parser.add_argument("--tier", choices=sorted(VALID_TIERS), default=None)
    parser.add_argument("--update-stale", action="store_true")
    parser.add_argument("--ignore-stale", action="store_true")
    parser.add_argument("--check-ollama", action="store_true", help="Check Ollama status during preflight")
    parser.add_argument("--prune-models", action="store_true", help="Remove unused models from Ollama to free up space")
    args = parser.parse_args()

    if args.prune_models:
        from ollama.self_healer import OllamaSelfHealer
        healer = OllamaSelfHealer()
        print(f"[OLLAMA] Pruning models not in primary whitelist ['{healer.primary_model}']...")
        removed = healer.prune_unused_models(keep_models=[healer.primary_model])
        print(f"[OLLAMA] Pruned {len(removed)} models: {removed}")
        return

    stale_mode = "update" if args.update_stale else ("ignore" if args.ignore_stale else "ask")
    ok, stale_files = run_preflight_checks(stale_mode=stale_mode, check_ollama=args.check_ollama)
    if not ok:
        sys.exit(1)

    agent_service = PcAgentService()

    if args.prompt:
        print(f"\n[CLI] Sending prompt to backend agent service...")
        result = agent_service.process_prompt(args.prompt)
    elif args.games or args.budget:
        games = args.games or ["minecraft", "roblox"]
        budget = args.budget or 3500.0
        print(f"[CLI] Requesting explicit build for {games} @ {budget} ILS...")
        result = agent_service.process_explicit(games, budget)
    else:
        result = agent_service.process_prompt("Build me a PC for Minecraft and Roblox with a budget of 3500 ILS")

    _display_all_tiers(result, filter_tier=args.tier)
    _display_stale_warning(stale_files)

if __name__ == "__main__":
    main()