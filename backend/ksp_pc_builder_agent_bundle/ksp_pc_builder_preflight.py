"""
Preflight checks for the KSP PC Builder Agent.

Checks performed
----------------
1. Presence and parse-validity of all catalog DB files.
2. Staleness — any file older than STALE_THRESHOLD_DAYS triggers a warning
   or an automatic update depending on stale_mode.

stale_mode values
-----------------
"ask"    — interactive prompt per stale file (default for interactive CLI runs)
"update" — auto-trigger update pipelines without prompting (--update-stale)
"ignore" — skip update, record stale files for end-of-run warning (--ignore-stale
           and all automatic / CI flows)

Return value
------------
run_preflight_checks() → (ok: bool, stale_files: list[str])

  ok          : False if any DB file is missing or unreadable.
  stale_files : names of DB files that exceeded the staleness threshold
                (populated regardless of stale_mode so the caller can always
                 surface the end-of-run warning).
"""

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple, List

from .ksp_pc_builder_config import Config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STALE_THRESHOLD_DAYS = 30

# All DB files checked for both presence and staleness.
ALL_DB_FILES: dict[str, Path] = {
    "parts_db":          Config.PARTS_DB_PATH,
    "game_requirements": Config.GAME_REQUIREMENTS_PATH,
    "known_games_urls":  Config.KNOWN_GAMES_URLS_PATH,
}

# Maps each DB name to the module path of its update pipeline.
# Pipelines are imported lazily so missing optional deps don't break startup.
UPDATE_PIPELINES: dict[str, str] = {
    "parts_db":
        "ksp_pc_builder_agent_bundle.data.pipelines.parts.download_parts_catalog",
    "game_requirements":
        "ksp_pc_builder_agent_bundle.data.pipelines.games.download_game_requirements",
    "known_games_urls":
        "ksp_pc_builder_agent_bundle.data.pipelines.games.update_known_games_urls",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trigger_update(db_name: str) -> None:
    """Dynamically import and run the update pipeline for the named DB."""
    module_path = UPDATE_PIPELINES.get(db_name)
    if not module_path:
        print(f"[PREFLIGHT] No update pipeline registered for '{db_name}'. Skipping.")
        return
    try:
        print(f"[PREFLIGHT] Triggering update pipeline for '{db_name}'...")
        mod = importlib.import_module(module_path)
        # Convention: every pipeline exposes a run() function as its entry point.
        if hasattr(mod, "run"):
            mod.run()
            print(f"[PREFLIGHT] Update complete for '{db_name}'.")
        else:
            print(
                f"[PREFLIGHT WARNING] Pipeline module '{module_path}' has no run() "
                f"function. Update skipped."
            )
    except Exception as e:
        print(
            f"[PREFLIGHT WARNING] Could not run update pipeline for '{db_name}': {e}",
            file=sys.stderr,
        )


def _check_staleness(
    db_name: str,
    db_path: Path,
    stale_mode: str,
    threshold: timedelta,
    now: datetime,
) -> bool:
    """
    Returns True if the file is stale.
    Side-effect: may trigger an update or prompt the user depending on stale_mode.
    """
    mtime     = datetime.fromtimestamp(db_path.stat().st_mtime)
    age       = now - mtime
    age_days  = age.days

    if age <= threshold:
        return False  # file is fresh

    print(
        f"[PREFLIGHT STALE] '{db_name}' is {age_days} day(s) old "
        f"(threshold: {threshold.days} days)"
    )

    if stale_mode == "update":
        _trigger_update(db_name)
    elif stale_mode == "ask":
        try:
            answer = input(f"  → Update '{db_name}' now? [y/N]: ").strip().lower()
        except EOFError:
            answer = "n"  # non-interactive context
        if answer == "y":
            _trigger_update(db_name)
    # stale_mode == "ignore" → no action, caller records as stale for end-of-run warning

    return True  # still stale even after update attempt (file may have just been refreshed)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_preflight_checks(stale_mode: str = "ask") -> Tuple[bool, List[str]]:
    """
    Validate all catalog DB files before the engine starts.

    Parameters
    ----------
    stale_mode : str
        "ask"    — interactive prompt when a file is stale (default)
        "update" — auto-trigger update pipelines without prompting
        "ignore" — record stale files but take no action

    Returns
    -------
    (ok, stale_files)
        ok          — False if any required DB file is missing or unreadable.
        stale_files — list of DB names that exceeded the staleness threshold.
    """
    print("[PREFLIGHT] Running diagnostic system checks...")

    if stale_mode not in ("ask", "update", "ignore"):
        print(
            f"[PREFLIGHT WARNING] Unknown stale_mode '{stale_mode}'. "
            f"Defaulting to 'ignore'.",
            file=sys.stderr,
        )
        stale_mode = "ignore"

    now       = datetime.now()
    threshold = timedelta(days=STALE_THRESHOLD_DAYS)

    stale_files: List[str] = []
    all_ok = True

    for db_name, db_path in ALL_DB_FILES.items():
        # ── 1. Existence check ────────────────────────────────────────────
        if not db_path.exists():
            print(
                f"[PREFLIGHT ERROR] Missing DB file: '{db_name}' → {db_path}",
                file=sys.stderr,
            )
            all_ok = False
            continue

        # ── 2. Parse-validity check ───────────────────────────────────────
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Quick sanity: top-level must be a dict or list
            if not isinstance(data, (dict, list)):
                raise ValueError("Top-level JSON value is neither an object nor an array.")
            print(f"[PREFLIGHT] '{db_name}': OK")
        except Exception as e:
            print(
                f"[PREFLIGHT ERROR] DB '{db_name}' failed validation: {e}",
                file=sys.stderr,
            )
            all_ok = False
            continue

        # ── 3. Staleness check ────────────────────────────────────────────
        is_stale = _check_staleness(db_name, db_path, stale_mode, threshold, now)
        if is_stale:
            stale_files.append(db_name)

    if all_ok:
        print(f"[PREFLIGHT] All {len(ALL_DB_FILES)} catalog files validated successfully.")
    return all_ok, stale_files


# ---------------------------------------------------------------------------
# Standalone runner (python -m ksp_pc_builder_agent_bundle.ksp_pc_builder_preflight)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KSP Preflight Diagnostic")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--update-stale", action="store_true")
    group.add_argument("--ignore-stale", action="store_true")
    cli_args = parser.parse_args()

    if cli_args.update_stale:
        mode = "update"
    elif cli_args.ignore_stale:
        mode = "ignore"
    else:
        mode = "ask"

    success, stale = run_preflight_checks(stale_mode=mode)
    if stale:
        print(f"\n[PREFLIGHT] Stale files: {', '.join(stale)}")
    sys.exit(0 if success else 1)