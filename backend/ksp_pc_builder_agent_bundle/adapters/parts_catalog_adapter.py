"""
Parts Catalog Adapter — runtime query interface.

Delegates to CatalogDB (in-memory SQLite) for O(log N) indexed lookups
instead of full-table JSON scans. The JSON source files are unchanged;
CatalogDB reads them once at startup.
"""

from pathlib import Path
from typing import Optional

from ksp_pc_builder_agent_bundle.ksp_pc_builder_config import Config
from ksp_pc_builder_agent_bundle.data.common.db import CatalogDB

GPU_VALID_KEYWORDS   = ["rtx", "gtx", "rx", "radeon", "geforce", "arc", "graphics card"]
GPU_EXCLUDE_KEYWORDS = ["holder", "bracket", "support", "cable", "riser", "backplate", "stand"]


class PartsCatalogAdapter:
    def __init__(self, db_path: Path | str | None = None, db: "CatalogDB | None" = None):
        if db is not None:
            # Accept a pre-built shared CatalogDB (from the engine, to avoid double-loading)
            self._db = db
        else:
            parts_path = Path(db_path) if db_path else Config.PARTS_DB_PATH
            self._db = CatalogDB(parts_db_path=parts_path)

    def get_category(self, category: str, max_price: Optional[float] = None) -> list:
        """Return parts in *category*, optionally filtered to ≤ max_price, sorted ascending."""
        return self._db.get_parts_by_category(category, max_price=max_price)

    def get_items_by_category(self, category: str, max_price: Optional[float] = None) -> list:
        """Alias kept for engine compatibility."""
        return self.get_category(category, max_price=max_price)

    def get_best_gpu(self, max_price: float) -> dict | None:
        """Return the highest-priced (most powerful) real GPU within max_price."""
        gpus = self.get_category("gpu", max_price=max_price)
        valid_gpus = []

        for g in gpus:
            name_lower = g.get("name", "").lower()
            if any(ex in name_lower for ex in GPU_EXCLUDE_KEYWORDS):
                continue
            if any(kw in name_lower for kw in GPU_VALID_KEYWORDS) or g.get("price", 0) > 250:
                valid_gpus.append(g)

        if not valid_gpus:
            return None

        valid_gpus.sort(key=lambda x: x.get("price", 0), reverse=True)
        return valid_gpus[0]