"""
In-memory SQLite catalog database.

Why SQLite over raw JSON at runtime
-------------------------------------
The JSON files remain the authoritative source-of-truth (human-readable, git-diff
friendly, written by the pipeline scripts). At agent startup the JSON files are
imported into an in-memory SQLite database so that:

  • Compatibility lookups use indexed queries instead of full-table scans.
  • get_parts_by_category() is O(log N) instead of O(N).
  • Future queries (e.g. "all DDR5 motherboards under 1500 ILS") are expressible
    as simple SQL without nested Python comprehensions.

No new third-party packages are required — sqlite3 is Python stdlib.

Usage
-----
    from ksp_pc_builder_agent_bundle.data.common.db import CatalogDB

    db = CatalogDB()                         # loads all catalogs on first access
    parts = db.get_parts_by_category("gpu")
    specs = db.get_specs("cpus", "Ryzen 5 5600X")
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from ksp_pc_builder_agent_bundle.ksp_pc_builder_config import Config

logger = logging.getLogger("KspAgentEngine")


class CatalogDB:
    """
    Lightweight in-memory SQLite layer over the JSON catalog files.

    The database is populated once from the JSON source files and reused
    for the lifetime of the process. All tables are in-memory only
    (``database=":memory:"``), so there is no risk of stale on-disk SQLite state.
    """

    # -----------------------------------------------------------------------
    # Schema
    # -----------------------------------------------------------------------
    _DDL = """
    CREATE TABLE IF NOT EXISTS parts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT    NOT NULL,
        name        TEXT    NOT NULL,
        price       REAL    DEFAULT 0.0,
        description TEXT,
        raw_json    TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_parts_category ON parts(category);
    CREATE INDEX IF NOT EXISTS idx_parts_price     ON parts(category, price);

    CREATE TABLE IF NOT EXISTS specs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        db_category     TEXT NOT NULL,
        name            TEXT NOT NULL,
        socket          TEXT,
        memory_type     TEXT,
        form_factor     TEXT,
        microarchitecture TEXT,
        raw_json        TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_specs_category ON specs(db_category);
    CREATE INDEX IF NOT EXISTS idx_specs_name     ON specs(db_category, name);
    """

    def __init__(
        self,
        parts_db_path: Optional[Path] = None,
        specs_db_path: Optional[Path] = None,
    ):
        self._parts_path = parts_db_path or Config.PARTS_DB_PATH
        self._specs_path = specs_db_path
        self._conn: sqlite3.Connection = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()

    # -----------------------------------------------------------------------
    # Public query API
    # -----------------------------------------------------------------------

    def get_parts_by_category(
        self,
        category: str,
        max_price: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return all parts in *category* (case-insensitive), optionally capped at
        *max_price*, sorted ascending by price.
        """
        if max_price is not None:
            rows = self._conn.execute(
                "SELECT raw_json FROM parts "
                "WHERE category = ? AND price <= ? ORDER BY price ASC",
                (category.lower(), max_price),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT raw_json FROM parts "
                "WHERE category = ? ORDER BY price ASC",
                (category.lower(),),
            ).fetchall()

        return [json.loads(r["raw_json"]) for r in rows]

    def get_specs(self, db_category: str, name: str) -> Optional[Dict[str, Any]]:
        """
        Return the spec record for *name* within *db_category* (e.g. "cpus").
        Uses substring matching to tolerate minor name differences.
        Returns None if no match is found.
        """
        name_lower = name.lower()
        # Try exact/substring match via LIKE on the lowercased name column.
        # SQLite LIKE is case-insensitive for ASCII by default.
        row = self._conn.execute(
            "SELECT raw_json FROM specs "
            "WHERE db_category = ? AND (LOWER(name) LIKE ? OR ? LIKE '%' || LOWER(name) || '%') "
            "LIMIT 1",
            (db_category, f"%{name_lower}%", name_lower),
        ).fetchone()
        return json.loads(row["raw_json"]) if row else None

    def get_categories(self) -> List[str]:
        """Return the distinct part categories present in the catalog."""
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM parts ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    # -----------------------------------------------------------------------
    # Internal — bootstrap
    # -----------------------------------------------------------------------

    def _bootstrap(self) -> None:
        """Create schema and import JSON files into in-memory tables."""
        self._conn.executescript(self._DDL)
        self._load_parts()
        self._load_specs()
        self._conn.commit()
        logger.info(
            f"[CatalogDB] In-memory SQLite ready — "
            f"{self._count('parts')} parts, {self._count('specs')} spec records."
        )

    def _load_parts(self) -> None:
        if not self._parts_path.exists():
            logger.warning(f"[CatalogDB] Parts DB not found at {self._parts_path}. Skipping.")
            return

        with open(self._parts_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        categories: Dict[str, List[Dict]] = raw.get("categories", {})
        rows = []
        for cat, items in categories.items():
            for item in items:
                rows.append((
                    cat.lower(),
                    item.get("name", ""),
                    float(item.get("price", 0.0)),
                    item.get("description", ""),
                    json.dumps(item, ensure_ascii=False),
                ))

        self._conn.executemany(
            "INSERT INTO parts (category, name, price, description, raw_json) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        logger.info(f"[CatalogDB] Loaded {len(rows)} parts from {self._parts_path.name}.")

    def _load_specs(self) -> None:
        if not self._specs_path or not self._specs_path.exists():
            return

        with open(self._specs_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        rows = []
        for db_cat, items in raw.items():
            if not isinstance(items, list):
                continue
            for item in items:
                rows.append((
                    db_cat,
                    item.get("name", ""),
                    item.get("socket"),
                    item.get("memory_type") or item.get("ram_type"),
                    item.get("form_factor"),
                    item.get("microarchitecture"),
                    json.dumps(item, ensure_ascii=False),
                ))

        self._conn.executemany(
            "INSERT INTO specs "
            "(db_category, name, socket, memory_type, form_factor, microarchitecture, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        logger.info(f"[CatalogDB] Loaded {len(rows)} spec records from {self._specs_path.name}.")

    def _count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
