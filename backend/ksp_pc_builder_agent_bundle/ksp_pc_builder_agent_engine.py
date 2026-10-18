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


VALID_STRATEGIES = {"minimal", "best_gpu", "best_cpu", "balanced"}

TIER_LABELS = {
    "minimal":    "Minimal Compatible Build",
    "best_gpu":   "Best GPU Build",
    "best_cpu":   "Best CPU Build",
    "budget_60":  "Optional Build — 60% of budget",
    "budget_80":  "Optional Build — 80% of budget",
    "budget_100": "Optional Build — 100% of budget (balanced)",
}

CATEGORY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "balanced": {
        "gpu": 0.42,
        "cpu": 0.22,
        "motherboard": 0.12,
        "ram": 0.08,
        "ssd": 0.08,
        "psu": 0.05,
        "case": 0.03,
    },
    "best_gpu": {
        "gpu": 0.55,
        "cpu": 0.22,
        "motherboard": 0.09,
        "ram": 0.07,
        "ssd": 0.05,
        "psu": 0.04,
        "case": 0.02,
    },
    "best_cpu": {
        "cpu": 0.40,
        "gpu": 0.25,
        "motherboard": 0.14,
        "ram": 0.09,
        "ssd": 0.05,
        "psu": 0.04,
        "case": 0.03,
    },
}


class KspPcBuilderAgentEngine:
    """Agent Engine that builds balanced PCs based on target games and budget targets."""

    SELECTION_ORDER = ["cpu", "motherboard", "ram", "gpu", "ssd", "psu", "case"]

    def __init__(self, catalog_path: Optional[str] = None):
        logger.info("Initializing KSP PC Builder Agent Engine...")
        from .data.common.db import CatalogDB
        parts_path = Path(catalog_path) if catalog_path else None
        shared_db = CatalogDB(parts_db_path=parts_path)
        self.catalog = PartsCatalogAdapter(db=shared_db)
        self.compatibility = PCCompatibilityRules()
        self.game_rules = GameRequirementsRules()

    def process_build_request_tiered(
        self, games: List[str], max_budget: float
    ) -> Dict[str, Any]:
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

        # ── Tier 1: Minimal (Finds Global Minimum Total Cost Build) ──
        minimal = self._build_minimal_optimal(reqs, max_budget)
        tiers["minimal"] = minimal

        minimal_is_complete = len(minimal["missing_categories"]) == 0

        minimal_is_viable = minimal["within_budget"] and minimal_is_complete

        if not minimal_is_viable:
            delta = minimal["total_price"] - max_budget
            if not minimal["within_budget"]:
                msg = (
                    f"Budget of {max_budget:.2f} ILS is below the minimum complete build cost "
                    f"of {minimal['total_price']:.2f} ILS (Delta needed: +{delta:.2f} ILS)."
                )
            else:
                msg = (
                    f"Could not construct a complete build within {max_budget:.2f} ILS. "
                    f"Missing categories: {', '.join(minimal['missing_categories'])}."
                )
            warnings.append(msg)
            logger.warning(msg)
            return {
                "requested_games": games,
                "target_budget": max_budget,
                "requirements": reqs,
                "tiers": tiers,
                "warnings": warnings,
                "min_cost_delta": delta if not minimal["within_budget"] else 0.0,
            }

        # ── Tiers 2–6: Strategy Tiers ────────────────────────────────
        for key, strategy, budget_mult in [
            ("best_gpu",   "best_gpu",  1.0),
            ("best_cpu",   "best_cpu",  1.0),
            ("budget_60",  "balanced",  0.6),
            ("budget_80",  "balanced",  0.8),
            ("budget_100", "balanced",  1.0),
        ]:
            tier_budget = max_budget * budget_mult
            t_res = self._build_one(reqs, tier_budget, strategy=strategy)
            if t_res["within_budget"] and len(t_res["missing_categories"]) == 0:
                tiers[key] = t_res

        return {
            "requested_games": games,
            "target_budget": max_budget,
            "requirements": reqs,
            "tiers": tiers,
            "warnings": warnings,
        }

    def process_build_request(
        self, games: List[str], max_budget: float
    ) -> Dict[str, Any]:
        result = self.process_build_request_tiered(games, max_budget)
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

    def _build_minimal_optimal(self, reqs: Dict[str, Any], budget: float) -> Dict[str, Any]:
        """
        Evaluate candidate CPUs across platforms (AMD & Intel) to discover
        the overall global minimal-cost complete build rather than naively
        picking the single cheapest CPU.
        """
        all_cpus = self.catalog.get_items_by_category("cpu")
        if not all_cpus:
            return self._build_one(reqs, budget, strategy="minimal")

        # Sort CPUs by price ascending
        sorted_cpus = sorted(all_cpus, key=lambda x: x.get("price", 0.0))

        best_build: Optional[Dict[str, Any]] = None
        min_total_price = float("inf")

        for cpu_candidate in sorted_cpus:
            # If the CPU alone is already more expensive than a found complete build, prune search
            if cpu_candidate.get("price", 0.0) >= min_total_price:
                break

            initial_build = {"cpu": cpu_candidate}
            candidate_res = self._build_one(
                reqs, budget, strategy="minimal", initial_build=initial_build
            )

            # Check if this configuration produced a complete build
            if len(candidate_res["missing_categories"]) == 0:
                cost = candidate_res["total_price"]
                if cost < min_total_price:
                    min_total_price = cost
                    best_build = candidate_res

        # Fallback to default single-pass build if no complete build was formed
        if best_build is None:
            return self._build_one(reqs, budget, strategy="minimal")

        return best_build

    def _build_one(
        self,
        reqs: Dict[str, Any],
        budget: float,
        strategy: str = "balanced",
        initial_build: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Unknown strategy '{strategy}'. Must be one of {VALID_STRATEGIES}.")

        selection_order = list(self.SELECTION_ORDER)
        if strategy == "best_gpu":
            selection_order = ["cpu", "motherboard", "gpu", "ram", "ssd", "psu", "case"]
        elif strategy == "best_cpu":
            selection_order = ["cpu", "motherboard", "ram", "gpu", "ssd", "psu", "case"]

        selected_build: Dict[str, Any] = dict(initial_build) if initial_build else {}
        total_cost = sum(part.get("price", 0.0) for part in selected_build.values())
        missing: List[str] = []

        weights = CATEGORY_WEIGHTS.get(strategy, CATEGORY_WEIGHTS["balanced"])

        for category in selection_order:
            if category in selected_build:
                continue

            items = self.catalog.get_items_by_category(category)

            if not items:
                logger.warning(f"No items in catalog for category '{category}'")
                missing.append(category)
                continue

            remaining_total_budget = budget - total_cost

            if strategy == "minimal":
                category_budget_cap = remaining_total_budget
            else:
                weighted_cap = budget * weights.get(category, 0.10)
                category_budget_cap = min(remaining_total_budget, max(weighted_cap, remaining_total_budget * 0.15))

                if strategy == "best_gpu" and category == "cpu":
                    category_budget_cap = max(category_budget_cap, budget * 0.22)
                if strategy == "best_cpu" and category == "gpu":
                    category_budget_cap = max(category_budget_cap, budget * 0.25)

            candidate = self._select_best_candidate(
                category, items, reqs, category_budget_cap, selected_build, strategy
            )

            # Fallback relaxation under remaining budget
            if not candidate and strategy != "minimal":
                candidate = self._select_best_candidate(
                    category, items, reqs, remaining_total_budget, selected_build, strategy="minimal"
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
                    f"within budget cap ({category_budget_cap:.2f} ILS)."
                )
                missing.append(category)

        return {
            "strategy": strategy,
            "budget": budget,
            "total_price": total_cost,
            "within_budget": total_cost <= budget,
            "build": selected_build,
            "missing_categories": missing,
        }

    def _select_best_candidate(
        self,
        category: str,
        items: List[Dict[str, Any]],
        reqs: Dict[str, Any],
        remaining_budget: float,
        current_build: Dict[str, Any],
        strategy: str = "balanced",
    ) -> Optional[Dict[str, Any]]:

        compatible_candidates: List[Dict[str, Any]] = []
        for item in items:
            is_compat, reason = self.compatibility.is_compatible(
                category, item, current_build
            )
            if is_compat:
                compatible_candidates.append(item)

        if not compatible_candidates:
            return None

        descending = (
            (strategy == "best_gpu" and category in ("gpu", "cpu")) or
            (strategy == "best_cpu" and category in ("cpu", "gpu")) or
            (strategy == "balanced" and category in ("gpu", "cpu"))
        )
        sorted_candidates = sorted(
            compatible_candidates,
            key=lambda x: x.get("price", 0.0),
            reverse=descending,
        )

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
                return affordable_gpus[0]
            return None

        if category == "ram":
            target_ram = reqs["required_ram_gb"]
            for item in sorted_candidates:
                name = item.get("name", "")
                if f"{target_ram}GB" in name or f"{target_ram}GB" in item.get("description", ""):
                    if strategy == "minimal" or item.get("price", 0.0) <= remaining_budget:
                        return item
            for item in sorted_candidates:
                if strategy == "minimal" or item.get("price", 0.0) <= remaining_budget:
                    return item
            return None

        if strategy == "minimal":
            cheapest = sorted(sorted_candidates, key=lambda x: x.get("price", 0.0))
            return cheapest[0] if cheapest else None

        affordable = [i for i in sorted_candidates if i.get("price", 0.0) <= remaining_budget]
        return affordable[0] if affordable else None