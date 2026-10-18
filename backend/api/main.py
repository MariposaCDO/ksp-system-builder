import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Path bootstrap
API_DIR = Path(__file__).resolve().parent
BACKEND_DIR = API_DIR.parents[0]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ksp_pc_builder_agent_bundle import run_preflight_checks
from api.routes import build_router, games_router, components_router

def create_app() -> FastAPI:
    app = FastAPI(
        title="KSP System Builder API",
        version="1.1.0",
        description="REST API for PC System Builder recommendations, game requirements, and component queries.",
    )

    # Enable CORS for browser / web UI clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include modular routers
    app.include_router(build_router)
    app.include_router(games_router)
    app.include_router(components_router)

    @app.on_event("startup")
    def startup_event():
        ok, stale_files = run_preflight_checks(stale_mode="ignore")
        if not ok:
            print("[WARNING] Preflight checks encountered errors during startup.")

    return app

app = create_app()