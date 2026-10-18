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

## Runtime Mutation

While pipelines handle bulk/offline ETL, `catalogs/games/game_requirements.json` can also be queried and mutated at runtime through the backend API:
- `GET /api/v1/games` — list all recognized games
- `POST /api/v1/games/upsert` — canonical upsert mechanism (in-memory + persists to JSON)
- `POST /api/v1/games/add` — wrapper that fails with 409 if game already exists
- `PUT /api/v1/games/update` — wrapper that fails with 404 if game is missing

