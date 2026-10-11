# Data layout

| Area | Role |
| --- | --- |
| `catalogs/` | JSON the agent loads at runtime |
| `pipelines/` | ETL only — not imported by the build engine |
| `common/` | Shared paths and JSON helpers |

## Pipeline contract

| Prefix | Behavior |
| --- | --- |
| `download_*` | Replace the target catalog from an external source |
| `update_*` | Read existing catalog, patch specific entries, write back |

## Catalog paths

- `catalogs/parts/parts_db.json`
- `catalogs/games/game_requirements.json`
- `catalogs/games/known_games_url.json`

Run pipelines from `agent/ksp-system-builder` with `backend` on `PYTHONPATH`, or invoke the script paths shown in the project README.
