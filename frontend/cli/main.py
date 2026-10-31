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
from ksp_pc_builder_agent_bundle import run_preflight_checks, check_games_in_catalog
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


def _handle_missing_games(missing_games: list) -> bool:
    """
    Interactively prompt the user to fetch missing games from SRL or quit.

    Tries to resolve the best SRL URL for each missing game using the existing
    srl_client (which canonicalizes Roman numerals, e.g. 'iv' -> '4' and vice-versa).

    Returns True if all games were successfully fetched and the build should continue,
    or False if the user chose to quit.
    """
    from ksp_pc_builder_agent_bundle.data.pipelines.games.srl_client import resolve_best_srl_game
    from ksp_pc_builder_agent_bundle.data.pipelines.games.update_game_requirements import update_single_game

    print("\n" + "=" * 80)
    print(f"[PREFLIGHT] Game(s) not found in local catalog: {', '.join(missing_games)}")
    print("=" * 80)

    all_fetched = True

    for game_slug in missing_games:
        print(f"\n[PREFLIGHT] Resolving '{game_slug}' against SystemRequirementsLab...")

        # Try to resolve the SRL match to show the user what we found
        srl_match = None
        resolved_url = None
        try:
            srl_match = resolve_best_srl_game(game_slug)
            if srl_match and srl_match.get("url"):
                resolved_url = srl_match["url"]
                resolved_title = srl_match.get("title", game_slug)
                print(f"  -> Found on SRL: '{resolved_title}'")
                print(f"     URL: {resolved_url}")
            else:
                print(f"  -> Could not auto-resolve '{game_slug}' on SRL.")
        except Exception as e:
            print(f"  -> SRL lookup error: {e}")

        print()
        print(f"  Options for '{game_slug}':")
        if resolved_url:
            print(f"  [F] Fetch requirements from SRL now  ({resolved_url})")
        else:
            print(f"  [F] Fetch requirements from SRL now  (will attempt search: '{game_slug}')")
        print(f"  [Q] Quit — stop the build")
        print()

        while True:
            try:
                choice = input("  Your choice [F/Q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"

            if choice in ("f", "fetch"):
                print(f"\n[PREFLIGHT] Fetching game requirements for '{game_slug}'...")
                try:
                    success = update_single_game(game_slug, url=resolved_url)
                    if success:
                        print(f"[PREFLIGHT] '{game_slug}' successfully added to catalog. Continuing build.\n")
                    else:
                        print(f"[PREFLIGHT ERROR] Could not fetch requirements for '{game_slug}'.")
                        print(f"  You can add it manually via:")
                        print(f'  python backend/ksp_pc_builder_agent_bundle/data/pipelines/games/update_game_requirements.py --game "{game_slug}" --url <SRL_URL>')
                        all_fetched = False
                except Exception as e:
                    print(f"[PREFLIGHT ERROR] Fetch failed: {e}")
                    all_fetched = False
                break

            elif choice in ("q", "quit"):
                print(f"\n[PREFLIGHT] Build cancelled by user.")
                return False

            else:
                print("  Please enter F to fetch or Q to quit.")

    return all_fetched


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

    # ── Determine games early (needed for preflight game check) ──────────────
    # We do a lightweight parse here to extract the game list before running
    # the full agent service — this lets preflight block before any heavy work.
    games_for_preflight: list = []
    if args.games:
        games_for_preflight = args.games
    elif args.prompt:
        # Quick deterministic extraction — same regex as agent_service fallback
        text = args.prompt.strip()
        text = re.sub(r"\b(?:with\s+a\s+budget\s+of|with\s+budget\s+of|budget\s+of|with\s+a\s+budget|budget)\s*(?:of\s*)?\d+(?:\.\d+)?\s*(?:ils|nis|₪)?\b", "", text, flags=re.I)
        text = re.sub(r"\bwith\s+\d+(?:\.\d+)?\s*(?:ils|nis|₪)\b", "", text, flags=re.I)
        text = re.sub(r"\bunder\s+\d+(?:\.\d+)?\s*(?:ils|nis|₪)?\b", "", text, flags=re.I)
        text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ils|nis|₪)\b", "", text, flags=re.I)
        text = re.sub(r"^(?:please\s+)?(?:build|make|give|recommend)\s+(?:me\s+)?(?:a\s+)?(?:pc|computer|system|rig)\s+(?:for|to\s+play)\s+", "", text, flags=re.I)
        text = re.sub(r"^(?:i\s+want\s+to\s+play|i\s+need\s+a\s+pc\s+for)\s+", "", text, flags=re.I)
        text = re.sub(r"\bwith\s+a\s*$", "", text, flags=re.I).strip()
        parts = re.split(r"\s+(?:and|&|\+)\s+|,", text, flags=re.I)
        stop_words = {"i want", "pc", "a", "for", "with", "the", "play", "to", "under", "budget", "of"}
        for p in parts:
            g_str = p.strip()
            if g_str and g_str.lower() not in stop_words:
                games_for_preflight.append(g_str)

    # ── Preflight: check if all requested games are in the catalog ────────────
    if games_for_preflight:
        missing_games = check_games_in_catalog(games_for_preflight)
        if missing_games:
            should_continue = _handle_missing_games(missing_games)
            if not should_continue:
                sys.exit(1)

    # ── Run the build ─────────────────────────────────────────────────────────
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

    # Guard: Fail if any requested game is still unrecognized after preflight
    unrecognized = result.get("requirements", {}).get("unrecognized_games", [])
    if unrecognized:
        missing_str = ", ".join(unrecognized)
        print("\n" + "=" * 80)
        print(f"[ERROR] Game(s) missing from database: {missing_str}")
        print(f"[HINT] Game '{unrecognized[0]}' was not found in the requirements catalog.")
        print(f"       You can add it via the API by posting to /api/v1/games/upsert or /api/v1/games/add:")
        print(f'       {{"game": "{unrecognized[0]}", "required_ram_gb": 16, "required_vram_gb": 6}}')
        print(f'       Or update offline: python backend/ksp_pc_builder_agent_bundle/data/pipelines/games/update_game_requirements.py --game "{unrecognized[0]}" --url <SRL_URL>')
        print("=" * 80)
        sys.exit(1)

    _display_all_tiers(result, filter_tier=args.tier)
    _display_stale_warning(stale_files)


if __name__ == "__main__":
    main()
