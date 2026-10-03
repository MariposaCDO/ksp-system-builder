import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from .adapters.parts_catalog_adapter import PartsCatalogAdapter
from .domain.game_requirements_rules import GameRequirementsRules
from .domain.pc_compatibility_rules import PCCompatibilityRules

logger = logging.getLogger("KspAgentEngine")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[AGENT LOG] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------
# strategy controls sort priority for each component category during selection:
#   "minimal"   — cheapest compatible part wins every category
#   "best_gpu"  — GPU sorted descending (most powerful), all others ascending
#   "best_cpu"  — CPU sorted descending (most powerful), all others ascending
#   "balanced"  — GPU sorted descending within budget, others ascending (original behaviour)
VALID_STRATEGIES = {"minimal", "best_gpu", "best_cpu", "balanced"}

TIER_LABELS = {
    "minimal":    "Minimal Compatible Build",
    "best_gpu":   "Best GPU Build",
    "best_cpu":   "Best CPU Build",
    "budget_60":  "Optional Build — 60% of budget",
    "budget_80":  "Optional Build — 80% of budget",
    "budget_100": "Optional Build — 100% of budget (balanced)",
}


class KspPcBuilderAgentEngine:
    """Agent Engine that builds balanced PCs based on target games and budget targets."""

    # Component selection order — CPU first so socket is known before MB is picked.
    # RAM type is derived from MB. GPU has no socket dependency.
    SELECTION_ORDER = ["cpu", "motherboard", "ram", "gpu", "ssd", "psu", "case"]

    def __init__(self, catalog_path: Optional[str] = None):
        logger.info("Initializing KSP PC Builder Agent Engine...")
        from .data.common.db import CatalogDB
        # Single shared DB instance — avoids loading 30k+ records twice
        parts_path = Path(catalog_path) if catalog_path else None
        shared_db = CatalogDB(parts_db_path=parts_path)
        self.catalog = PartsCatalogAdapter(db=shared_db)
        self.compatibility = PCCompatibilityRules(specs_db=shared_db)
        self.game_rules = GameRequirementsRules()

    # ------------------------------------------------------------------
    # Public API — tiered (new primary method)
    # ------------------------------------------------------------------

    def process_build_request_tiered(
        self, games: List[str], max_budget: float
    ) -> Dict[str, Any]:
        """
        Produces up to 5 build tiers anchored to the game requirements:

        1. minimal   — cheapest compatible set (always attempted; anchor / fallback)
        2. best_gpu  — strongest GPU within budget (only when minimal succeeds)
        3. best_cpu  — strongest CPU within budget (only when minimal succeeds)
        4. budget_60 — balanced at 60 % of max_budget
        5. budget_80 — balanced at 80 % of max_budget
        6. budget_100— balanced at 100 % of max_budget

        If the budget is too small for even a minimal build, only the minimal tier
        is returned with ``within_budget: False`` and a clear warning message — the
        system still shows the cheapest available compatible build so the user knows
        what a real minimum would cost.
        """
        logger.info(
            f"Starting Tiered Build for Games: {games} | Max Budget: {max_budget} ILS"
        )

        reqs = self.game_rules.resolve_requirements(games)
        logger.info(
            f"Hardware Targets -> RAM >= {reqs['required_ram_gb']} GB "
            f"| VRAM >= {reqs['required_vram_gb']} GB"
        )

        tiers: Dict[str, Any] = {}
        warnings: List[str] = []

        # ── Tier 1: Minimal (always attempted) ──────────────────────────
        minimal = self._build_one(reqs, max_budget, strategy="minimal")
        tiers["minimal"] = minimal

        # A build is solved ONLY if all categories are present and within budget
        minimal_is_complete = len(minimal["missing_categories"]) == 0
        minimal_is_viable = minimal["within_budget"] and minimal_is_complete

        if not minimal_is_viable:
            delta = minimal["total_price"] - max_budget
            if not minimal["within_budget"]:
                msg = (
                    f"Budget of {max_budget:.2f} ILS is below the minimum complete build cost "
                    f"of {minimal['total_price']:.2f} ILS (Delta needed: +{delta:.2f} ILS). "
                    f"Only minimal system is displayed."
                )
            else:
                msg = (
                    f"Could not construct a complete build within {max_budget:.2f} ILS. "
                    f"Missing categories: {', '.join(minimal['missing_categories'])}. "
                    f"Only minimal partial build is displayed."
                )
            warnings.append(msg)
            logger.warning(msg)
            # Return early with only minimal tier per requirement 2.2 & 2.3
            return {
                "requested_games": games,
                "target_budget": max_budget,
                "requirements": reqs,
                "tiers": tiers,
                "warnings": warnings,
                "min_cost_delta": delta if not minimal["within_budget"] else 0.0,
            }

        # ── Tiers 2–6: Premium / optional (only when minimal is completely solved and within budget) ──
        for key, strategy, budget_mult in [
            ("best_gpu",   "best_gpu",  1.0),
            ("best_cpu",   "best_cpu",  1.0),
            ("budget_60",  "balanced",  0.6),
            ("budget_80",  "balanced",  0.8),
            ("budget_100", "balanced",  1.0),
        ]:
            tier_budget = max_budget * budget_mult
            t_res = self._build_one(reqs, tier_budget, strategy=strategy)
            # Only include optional build if it is fully solved (no missing categories) and within tier budget
            if t_res["within_budget"] and len(t_res["missing_categories"]) == 0:
                tiers[key] = t_res

        return {
            "requested_games": games,
            "target_budget": max_budget,
            "requirements": reqs,
            "tiers": tiers,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Public API — single build (backwards-compatible shim)
    # ------------------------------------------------------------------

    def process_build_request(
        self, games: List[str], max_budget: float
    ) -> Dict[str, Any]:
        """
        Legacy single-build method kept for backwards compatibility.
        Internally delegates to the tiered engine and returns the 'balanced'
        (budget_100) tier so existing callers continue to work unchanged.
        """
        result = self.process_build_request_tiered(games, max_budget)
        # Prefer balanced full-budget tier; fall back to minimal if that is all we have
        build_tier = result["tiers"].get("budget_100") or result["tiers"].get("minimal")
        return {
            "requested_games": games,
            "target_budget": max_budget,
            "total_price": build_tier["total_price"],
            "build": build_tier["build"],
            "requirements": result["requirements"],
            "within_budget": build_tier["within_budget"],
            "warnings": result.get("warnings", []),
        }

    # ------------------------------------------------------------------
    # Internal — single build for one strategy / budget
    # ------------------------------------------------------------------

    def _build_one(
        self,
        reqs: Dict[str, Any],
        budget: float,
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        """
        Selects one compatible set of parts using the given strategy within budget.

        Returns a build dict with keys: build, total_price, within_budget, missing_categories.
        """
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Unknown strategy '{strategy}'. Must be one of {VALID_STRATEGIES}.")

        # Strategy-tailored selection order:
        # best_gpu: Pick GPU first (or after CPU/MB if GPU dominates budget), but for best_gpu strategy,
        # picking GPU first allows maximizing GPU spend, then picking matching CPU, MB, RAM, peripherals.
        # best_cpu: CPU first, then Motherboard, RAM, GPU, SSD, PSU, Case.
        if strategy == "best_gpu":
            selection_order = ["gpu", "cpu", "motherboard", "ram", "ssd", "psu", "case"]
        elif strategy == "best_cpu":
            selection_order = ["cpu", "motherboard", "ram", "gpu", "ssd", "psu", "case"]
        else:
            selection_order = ["cpu", "motherboard", "ram", "gpu", "ssd", "psu", "case"]

        selected_build: Dict[str, Any] = {}
        total_cost = 0.0
        missing: List[str] = []

        for category in selection_order:
            items = self.catalog.get_items_by_category(category)
            if not items:
                logger.warning(f"No items in catalog for category '{category}'")
                missing.append(category)
                continue

            remaining = budget - total_cost
            candidate = self._select_best_candidate(
                category, items, reqs, remaining, selected_build, strategy
            )

            if candidate:
                selected_build[category] = candidate
                total_cost += candidate.get("price", 0.0)
                logger.info(
                    f"[{strategy.upper()}] Selected [{category.upper()}]: "
                    f"{candidate.get('name')} | {candidate.get('price')} ILS"
                )
            else:
                logger.warning(
                    f"[{strategy.upper()}] Could not find compatible [{category}] "
                    f"within remaining budget ({remaining:.2f} ILS)."
                )
                missing.append(category)

        # Fallback for premium/optional strategies: if greedy pass resulted in missing categories,
        # attempt to construct a valid build by taking the Minimal build as anchor and upgrading
        # the targeted component (GPU or CPU or balanced GPU) as much as remaining budget permits.
        if missing and strategy != "minimal":
            minimal_build = self._build_one(reqs, budget, strategy="minimal")
            if minimal_build["within_budget"] and not minimal_build["missing_categories"]:
                # Try upgrading target part in minimal build
                anchor = dict(minimal_build["build"])
                target_cat = "gpu" if strategy in ("best_gpu", "balanced") else "cpu"
                
                # Subtract target part cost from minimal total cost
                base_cost = minimal_build["total_price"] - anchor[target_cat].get("price", 0.0)
                upgrade_budget = budget - base_cost

                # Filter target part candidates compatible with anchor (excluding current target)
                partial_build = {k: v for k, v in anchor.items() if k != target_cat}
                target_items = self.catalog.get_items_by_category(target_cat)
                
                upgraded_part = self._select_best_candidate(
                    target_cat, target_items, reqs, upgrade_budget, partial_build, strategy
                )
                if upgraded_part and upgraded_part.get("price", 0.0) <= upgrade_budget:
                    anchor[target_cat] = upgraded_part
                    new_total = base_cost + upgraded_part.get("price", 0.0)
                    if new_total <= budget:
                        logger.info(
                            f"[{strategy.upper()}] Fallback upgrade successful: "
                            f"Upgraded {target_cat.upper()} to '{upgraded_part.get('name')}' "
                            f"(Total: {new_total:.2f} ILS)"
                        )
                        return {
                            "strategy": strategy,
                            "budget": budget,
                            "total_price": new_total,
                            "within_budget": True,
                            "build": anchor,
                            "missing_categories": [],
                        }

        return {
            "strategy": strategy,
            "budget": budget,
            "total_price": total_cost,
            "within_budget": total_cost <= budget,
            "build": selected_build,
            "missing_categories": missing,
        }

    # ------------------------------------------------------------------
    # Internal — candidate selection
    # ------------------------------------------------------------------

    def _select_best_candidate(
        self,
        category: str,
        items: List[Dict[str, Any]],
        reqs: Dict[str, Any],
        remaining_budget: float,
        current_build: Dict[str, Any],
        strategy: str = "balanced",
    ) -> Optional[Dict[str, Any]]:
        """Filters catalog candidates on specs, compatibility, and remaining budget."""

        # ── Compatibility filter ─────────────────────────────────────────
        compatible_candidates: List[Dict[str, Any]] = []
        for item in items:
            is_compat, reason = self.compatibility.is_compatible(
                category, item, current_build
            )
            if is_compat:
                compatible_candidates.append(item)
            else:
                logger.debug(
                    f"Skipping incompatible [{category}]: {item.get('name')} | {reason}"
                )

        if not compatible_candidates:
            logger.error(f"No compatible [{category}] found for current build specs!")
            return None

        # ── Strategy sort ────────────────────────────────────────────────
        # For the primary "power" component of each strategy, sort descending
        # so we naturally pick the most capable option within budget.
        descending = (
            (strategy == "best_gpu"  and category == "gpu") or
            (strategy == "best_cpu"  and category == "cpu") or
            (strategy == "balanced"  and category == "gpu")
        )
        sorted_candidates = sorted(
            compatible_candidates,
            key=lambda x: x.get("price", 0.0),
            reverse=descending,
        )

        # ── Special filter: GPU ──────────────────────────────────────────
        if category == "gpu":
            gpu_valid_kw  = ["rtx", "gtx", "rx", "radeon", "geforce", "arc", "graphics card"]
            gpu_exclude_kw = ["holder", "bracket", "support", "cable", "riser", "backplate", "stand"]

            real_gpus = [
                g for g in sorted_candidates
                if not any(ex in g.get("name", "").lower() for ex in gpu_exclude_kw)
                and (
                    any(kw in g.get("name", "").lower() for kw in gpu_valid_kw)
                    or g.get("price", 0.0) > 250
                )
            ]

            if strategy == "minimal" and real_gpus:
                cheapest_gpus = sorted(real_gpus, key=lambda x: x.get("price", 0.0))
                return cheapest_gpus[0]

            affordable_gpus = [g for g in real_gpus if g.get("price", 0.0) <= remaining_budget]
            if affordable_gpus:
                return affordable_gpus[0]  # already sorted per strategy
            return None

        # ── Special filter: RAM ──────────────────────────────────────────
        if category == "ram":
            target_ram = reqs["required_ram_gb"]
            for item in sorted_candidates:
                name = item.get("name", "")
                if f"{target_ram}GB" in name or f"{target_ram}GB" in item.get("description", ""):
                    if strategy == "minimal" or item.get("price", 0.0) <= remaining_budget:
                        return item
            # Fallback: any RAM if exact size not found
            for item in sorted_candidates:
                if strategy == "minimal" or item.get("price", 0.0) <= remaining_budget:
                    return item
            return None

        # ── Standard fallback ────────────────────────────────────────────
        if strategy == "minimal":
            cheapest = sorted(sorted_candidates, key=lambda x: x.get("price", 0.0))
            return cheapest[0] if cheapest else None

        affordable = [i for i in sorted_candidates if i.get("price", 0.0) <= remaining_budget]
        return affordable[0] if affordable else None