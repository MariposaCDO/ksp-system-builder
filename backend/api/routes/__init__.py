from api.routes.build import router as build_router
from api.routes.games import router as games_router
from api.routes.components import router as components_router

__all__ = ["build_router", "games_router", "components_router"]
