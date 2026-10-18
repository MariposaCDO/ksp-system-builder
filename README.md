# KSP PC Builder Agent

`Python 3.10+` `FastAPI REST API` `Ollama / Local LLM` `Deterministic Build Engine` `Live KSP Catalog`

A game-aware PC builder for KSP hardware. It resolves target game requirements, queries an indexed local KSP parts catalog (in-memory SQLite cache), enforces physical compatibility (socket, RAM type, form factor, TDP), and returns budgeted build recommendations across multiple budget tiers (`minimal`, `best_gpu`, `best_cpu`, `budget_60`, `budget_80`, `budget_100`).

Provides modular access through a **FastAPI REST API**, a **rich CLI**, and a lightweight **Web UI**. Optional Ollama integration turns natural-language prompts into games + budget constraints before handing off to the deterministic engine.

> **Recommended local models:** `llama3.1:8b`, `qwen2.5-coder:7b`, or `qwen2.5-coder:14b` via [Ollama](https://ollama.com) on port `11434`.

---

## Project Layout

```text
ksp-system-builder/
├── frontend/
│   ├── cli/
│   │   └── main.py              # CLI entrypoint (Ollama prompt or explicit flags)
│   └── html/
│       └── index.html           # Web UI interface
├── backend/
│   ├── api/                     # Modular FastAPI REST API layer
│   │   ├── main.py              # Application entrypoint & CORS middleware
│   │   ├── schemas.py           # Pydantic request models
│   │   ├── deps.py              # Dependency injection provider for services
│   │   └── routes/              # Modular API endpoints
│   │       ├── build.py         # /api/v1/build (prompt & explicit builds)
│   │       ├── games.py         # /api/v1/games (get, add, update, upsert)
│   │       └── components.py    # /api/v1/components (category & component queries)
│   ├── services/
│   │   └── agent_service.py     # Agent service bridging LLM prompt parsing & engine
│   ├── ollama/
│   │   └── self_healer.py       # Ollama health checks & auto-pull / model prune
│   └── ksp_pc_builder_agent_bundle/
│       ├── ksp_pc_builder_agent_engine.py   # Multi-tier deterministic build loop
│       ├── ksp_pc_builder_config.py         # Paths & env overrides
│       ├── ksp_pc_builder_preflight.py      # Catalog integrity & freshness checks
│       ├── adapters/
│       │   ├── parts_catalog_adapter.py     # Parts queries & best-GPU heuristics
│       │   └── web_scraper_adapter.py       # KSP item URL helpers
│       ├── domain/
│       │   ├── game_requirements_rules.py   # Game RAM/VRAM targets & mutation
│       │   └── pc_compatibility_rules.py    # Socket, RAM, and form-factor checks
│       └── data/
│           ├── README.md                    # Catalog vs pipeline contract
│           ├── catalogs/                    # Authoritative runtime JSON catalogs
│           │   ├── parts/parts_db.json
│           │   ├── games/game_requirements.json
│           │   └── games/known_games_url.json
│           ├── common/                      # In-memory SQLite DB, paths & JSON I/O
│           └── pipelines/                   # ETL (download = replace, update = patch)
│               ├── parts/download_parts_catalog.py
│               ├── games/download_game_requirements.py
│               ├── games/update_game_requirements.py
│               └── games/update_known_games_urls.py
└── README.md
```

---

## Quickstart & Standalone Setup

`ksp-system-builder` is fully decoupled and standalone. Commands below assume your working directory is `agent/ksp-system-builder`.

### 1. Automated One-Command Installer

**On Linux / macOS (Bash):**
```bash
chmod +x install.sh
./install.sh
```

**On Windows (PowerShell):**
```powershell
.\install.ps1
```

The installer will:
- Check Python `>= 3.10`
- Bootstrap [uv](https://astral.sh/uv) automatically
- Create `.venv` and install cryptographically hashed dependencies from `requirements.lock`
- Run catalog preflight checks
- Check and auto-heal Ollama model dependencies (`llama3.1:8b`)

---

### 2. Manual / UV Workflow

```bash
# Install uv if not already present
pip install uv

# Create isolated venv
uv venv .venv
source .venv/bin/activate    # On Windows: .\.venv\Scripts\Activate.ps1

# Install with hash verification
uv pip install --require-hashes -r requirements.lock

# Optional: re-compile dependencies when changing pyproject.toml
uv pip compile pyproject.toml --generate-hashes -o requirements.lock
```

---

### 3. Ollama & Model Self-Healer

The backend features an integrated self-healer (`backend/ollama/self_healer.py`) that:
- Verifies local Ollama service health.
- Automatically pulls the required model (`llama3.1:8b` or fallback `qwen2.5-coder:7b`) on demand if missing.
- Provides a model pruning CLI to clean up unused weights and free VRAM/disk:
  ```bash
  python frontend/cli/main.py --prune-models
  ```
- Gracefully falls back to deterministic rule extraction if Ollama is offline.

---

### 4. Ensure the Parts Database Exists

A catalog should already live at `backend/ksp_pc_builder_agent_bundle/data/catalogs/parts/parts_db.json`.
To regenerate it (fresh prices/inventory):

```bash
python backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py
```

Optional arguments:

```bash
python backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py --output backend/ksp_pc_builder_agent_bundle/data/catalogs/parts/parts_db.json
python backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py --comp-ids 16014 16015
python backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py --verbose
```

---

### 5. Running the Backend API Server

Start the FastAPI application with `uvicorn`:

```bash
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive Swagger / OpenAPI documentation is available at `http://localhost:8000/docs`.

#### API Endpoints Overview

| Category | Endpoint | Method | Description |
| --- | --- | --- | --- |
| **Build** | `/api/v1/build/prompt` | `POST` | Build PC configurations from a natural-language prompt |
| | `/api/v1/build/explicit` | `POST` | Build PC configurations for explicit games list and budget |
| **Games** | `/api/v1/games` | `GET` | List all supported games and their hardware requirements |
| | `/api/v1/games/upsert` | `POST` | **Canonical upsert** mechanism: creates or updates game requirements |
| | `/api/v1/games/add` | `POST` | Adds a new game requirement; fails with `409 Conflict` if existing |
| | `/api/v1/games/update` | `PUT` | Updates an existing game; fails with `404 Not Found` if missing |
| **Components** | `/api/v1/components/categories`| `GET` | List all 27 available hardware categories in the database |
| | `/api/v1/components/cpu` | `GET` | Retrieve all CPUs (supports optional `?max_price=` filter) |
| | `/api/v1/components/gpu` | `GET` | Retrieve all GPUs (supports optional `?max_price=` filter) |
| | `/api/v1/components/{category}`| `GET` | Retrieve parts by category (`motherboard`, `ram`, `ssd`, `psu`, etc.) |

> **Missing Game Guard:** Both the REST API and CLI normalize requested game titles (e.g. `sim6` $\rightarrow$ `sim 6`, `cyberpunk-2077` $\rightarrow$ `cyberpunk 2077`). If a requested game is not found in the requirements catalog, execution halts with a clear error referencing the normalized title that was searched, accompanied by a remediation hint showing how to add it via `/api/v1/games/upsert` or offline ETL.

---

### 6. Run the CLI Client

```bash
# Natural-language prompt (Ollama extracts games + budget, then runs the engine)
python frontend/cli/main.py --prompt "Build me a PC for Minecraft and Roblox with a budget of 3500 ILS"

# Explicit games + budget (no LLM required for the build itself)
python frontend/cli/main.py --games minecraft roblox --budget 3500

# View specific tier only (e.g. minimal, best_gpu, best_cpu, budget_100)
python frontend/cli/main.py --games minecraft roblox --budget 4500 --tier best_gpu

# Default demo prompt if no flags are given
python frontend/cli/main.py
```

---

## How It Works

1. **Game Requirements Evaluation** — `GameRequirementsRules` loads hardware targets from `game_requirements.json`. If a requested title is missing during build API calls, the system immediately halts with a helpful remediation hint.
2. **Indexed Catalog Queries** — At startup, `CatalogDB` loads `parts_db.json` into an in-memory SQLite database (`:memory:`) with indices on categories and prices for fast $O(\log N)$ filtered lookups without redundant file re-scans.
3. **Hardware Compatibility Verification** — `PCCompatibilityRules` validates physical constraints:
   - **Socket Matching:** CPU socket must match the motherboard socket (e.g. AM5, LGA1851, LGA1700).
   - **RAM Standard Matching:** Motherboard RAM type (DDR4 / DDR5) must match memory sticks.
   - **Chassis & Board Form Factors:** Motherboard form factor must be supported by the case (ATX, Micro-ATX, Mini-ITX).
   - **Thermal TDP Matching:** Cooler rating must equal or exceed CPU base power.
4. **Multi-Tier Budget Allocation** — `KspPcBuilderAgentEngine` computes multiple build strategies:
   - `minimal`: Minimum cost system meeting all game RAM and VRAM requirements.
   - `best_gpu`: Maximizes GPU spend (up to ~55% of budget) for peak graphical performance.
   - `best_cpu`: Prioritizes single-core and compute-heavy CPU performance (~40% of budget).
   - `budget_60`, `budget_80`, `budget_100`: Balanced allocations across tiers.

---

## Supporting Data Pipelines

Run from `agent/ksp-system-builder` (cwd). Scripts add `backend/` to `sys.path` automatically.

| Script | Op | Output | Purpose |
| --- | --- | --- | --- |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py` | download | catalogs/parts/parts_db.json | Full scrape of KSP components, prices, and stock |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/games/download_game_requirements.py` | download | catalogs/games/game_requirements.json | Rebuild game RAM/VRAM targets from known URLs |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/games/update_game_requirements.py` | update | patches game requirements + known URLs | Add or refresh a single game requirement offline |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/games/update_known_games_urls.py` | update | catalogs/games/known_games_url.json | Dedupe slugs and resolve SRL URLs |

---

## Configuration

| Setting | Where | Notes |
| --- | --- | --- |
| Parts DB path | `KSP_PARTS_DB_PATH` or `Config.PARTS_DB_PATH` | Defaults to bundle `catalogs/parts/parts_db.json` |
| Ollama model | `OLLAMA_MODEL` | Default `llama3.1:8b` |
| Ollama URL | `OLLAMA_URL` / `OLLAMA_BASE_URL` | Default `http://localhost:11434` |
| Auto heal models | `AUTO_HEAL_MODELS` | Default `true` |
| Build Budget / Games | CLI flags `--budget`, `--games` or API request payload | No need to edit engine source |

---

## Programmatic Use

```python
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path("backend").resolve()))

from ksp_pc_builder_agent_bundle import KspPcBuilderAgentEngine, run_preflight_checks

assert run_preflight_checks()
engine = KspPcBuilderAgentEngine()

# Generate tiered recommendations
result = engine.process_build_request_tiered(games=["minecraft", "roblox"], max_budget=4000.0)

for tier_name, tier_data in result["tiers"].items():
    print(f"Tier [{tier_name}]: Total = {tier_data['total_price']:.2f} ILS (Within budget: {tier_data['within_budget']})")
```
