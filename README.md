# KSP PC Builder Agent

`Python 3.10+` `Ollama / Local LLM` `Deterministic Build Engine` `Live KSP Catalog`

A game-aware PC builder for KSP hardware. It resolves target game requirements, queries a local KSP parts catalog, enforces physical compatibility (socket, RAM type, form factor), and returns a budgeted build recommendation.

Optional Ollama integration turns a natural-language prompt into games + budget, then hands off to the deterministic engine.

> **Recommended local models:** `llama3.1:8b`, `qwen2.5-coder:7b`, or `qwen2.5-coder:14b` via [Ollama](https://ollama.com) on port `11434`.

## Project Layout

```text
ksp-system-builder/
├── frontend/
│   └── cli/
│       └── main.py              # CLI entrypoint (Ollama prompt or explicit flags)
├── backend/
│   └── ksp_pc_builder_agent_bundle/
│       ├── ksp_pc_builder_agent_engine.py   # Core build loop
│       ├── ksp_pc_builder_config.py         # Paths / env overrides
│       ├── ksp_pc_builder_preflight.py      # Catalog presence check
│       ├── adapters/
│       │   ├── parts_catalog_adapter.py     # parts catalog queries
│       │   └── web_scraper_adapter.py       # KSP item URL helpers
│       ├── domain/
│       │   ├── game_requirements_rules.py   # Game RAM/VRAM targets
│       │   └── pc_compatibility_rules.py    # Socket / RAM / form-factor checks
│       └── data/
│           ├── README.md                    # catalogs vs pipelines contract
│           ├── catalogs/                    # Runtime JSON (agent loads these)
│           │   ├── parts/parts_db.json
│           │   ├── games/game_requirements.json
│           │   ├── games/known_games_url.json
│           │   └── compatibility/
│           │       ├── itemized_parts_specs.json
│           │       └── compatibility_db.json
│           ├── common/                      # Shared paths + JSON helpers
│           └── pipelines/                   # ETL (download = replace, update = patch)
│               ├── parts/download_parts_catalog.py
│               ├── games/download_game_requirements.py
│               ├── games/update_game_requirements.py
│               ├── games/update_known_games_urls.py
│               └── compatibility/
│                   ├── download_itemized_specs.py
│                   └── download_compatibility_db.py
├── docs/                                    # HTML architecture notes
└── README.md
```

## Quickstart

Commands below assume your cwd is `agent/ksp-system-builder`.

### 1. Install Dependencies

From the repo root:

```bash
pip install requests cloudscraper beautifulsoup4
```

(`requests` is already in the root `requirements.txt`. `cloudscraper` is required to refresh the KSP parts catalog.)

### 2. Ensure the Parts Database Exists

A catalog should already live at
`backend/ksp_pc_builder_agent_bundle/data/catalogs/parts/parts_db.json`.
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

**API sources:**
- `https://ksp.co.il/m_action/api/comp/16014` — Intel system builder catalog
- `https://ksp.co.il/m_action/api/comp/16015` — AMD system builder catalog

> KSP uses Cloudflare protection. The downloader uses `cloudscraper` to bypass it. On repeated 403s, wait ~30 seconds and retry.

Override the catalog path with `KSP_PARTS_DB_PATH` if needed.

### 3. (Optional) Set Up Ollama

```bash
ollama pull llama3.1:8b
# or: ollama pull qwen2.5-coder:7b
```

### 4. Run the CLI

```bash
# Natural-language prompt (Ollama extracts games + budget, then runs the engine)
python frontend/cli/main.py --prompt "Build me a PC for Minecraft and Roblox with a budget of 3500 ILS"

# Explicit games + budget (no LLM required for the build itself)
python frontend/cli/main.py --games minecraft roblox --budget 3500

# Default demo prompt if no flags are given
python frontend/cli/main.py
```

The CLI runs preflight (parts DB present and loadable), then prints a category / price / part summary table.

## How It Works

1. **Game requirements** — `GameRequirementsRules` looks up each game in
   `backend/ksp_pc_builder_agent_bundle/data/catalogs/games/game_requirements.json`.
   Unknown titles can be auto-fetched from System Requirements Lab and appended to the catalog.
2. **Catalog selection** — `PartsCatalogAdapter` loads parts by category
   (`cpu`, `motherboard`, `ram`, `ssd`, `psu`, `case`, `gpu`) from
   `backend/ksp_pc_builder_agent_bundle/data/catalogs/parts/parts_db.json`.
3. **Compatibility** — `PCCompatibilityRules` filters candidates against already-picked parts using
   `backend/ksp_pc_builder_agent_bundle/data/catalogs/compatibility/itemized_parts_specs.json`
   (socket, RAM type, form factor, etc.).
4. **Budget fit** — The engine picks lowest-price compatible parts within remaining budget and returns the build dict + totals.

## Supporting Data Pipelines

Run from `agent/ksp-system-builder` (cwd). Scripts add `backend/` to `sys.path` automatically.

| Script | Op | Output | Purpose |
| --- | --- | --- | --- |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/parts/download_parts_catalog.py` | download | catalogs/parts/parts_db.json | KSP prices / stock / categories |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/games/download_game_requirements.py` | download | catalogs/games/game_requirements.json | Rebuild game RAM/VRAM from known URLs |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/games/update_game_requirements.py` | update | patches game requirements + known URLs | Add or refresh a single game |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/games/update_known_games_urls.py` | update | catalogs/games/known_games_url.json | Dedupe slugs and resolve SRL URLs |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/compatibility/download_itemized_specs.py` | download | catalogs/compatibility/itemized_parts_specs.json | Specs for compatibility checks |
| `backend/ksp_pc_builder_agent_bundle/data/pipelines/compatibility/download_compatibility_db.py` | download | catalogs/compatibility/compatibility_db.json | Extra compatibility metadata |

Output paths are under `backend/ksp_pc_builder_agent_bundle/data/catalogs/`.

## Parts Database Shape

`backend/ksp_pc_builder_agent_bundle/data/catalogs/parts/parts_db.json` looks like:

```json
{
  "downloaded_at": "2026-09-22T19:01:55Z",
  "sources": ["https://ksp.co.il/m_action/api/comp/16014", "..."],
  "categories": {
    "cpu": [ { "uin": "...", "name": "...", "price": 369.0, "stock": 1 } ],
    "gpu": [],
    "motherboard": [],
    "ram": [],
    "psu": [],
    "case": [],
    "ssd": [],
    "hdd": [],
    "cpu_cooler": []
  }
}
```

Typical item fields: uin, uinsql, name, brand, price (ILS), stock, category_slug, ksp_url, eol, tags.

## Configuration

| Setting | Where | Notes |
| --- | --- | --- |
| Parts DB path | `KSP_PARTS_DB_PATH` or `Config.PARTS_DB_PATH` | Defaults to bundle catalogs/parts/parts_db.json (see Config) |
| Ollama model | `frontend/cli/main.py` (`MODEL`) | Default `llama3.1:8b` |
| Ollama URL | `frontend/cli/main.py` (`OLLAMA_URL`) | Default `http://localhost:11434/api/chat` |
| Budget / games | CLI `--budget` / `--games` or `--prompt` | No need to edit engine source |

## Programmatic Use

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend").resolve()))  # from ksp-system-builder/

from ksp_pc_builder_agent_bundle import KspPcBuilderAgentEngine, run_preflight_checks

assert run_preflight_checks()
engine = KspPcBuilderAgentEngine()
result = engine.process_build_request(games=["minecraft", "roblox"], max_budget=3500.0)
print(result["total_price"], result["build"].keys())
```
