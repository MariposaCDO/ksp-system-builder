from fastapi import APIRouter, HTTPException, Depends
from services.agent_service import PcAgentService
from api.schemas import GameUpsertRequest
from api.deps import get_agent_service

router = APIRouter(prefix="/api/v1/games", tags=["games"])

@router.get("")
def get_all_games(agent_service: PcAgentService = Depends(get_agent_service)):
    """Retrieve all games currently available in the requirements catalog."""
    try:
        return agent_service.get_all_games()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upsert")
def upsert_game(req: GameUpsertRequest, agent_service: PcAgentService = Depends(get_agent_service)):
    """
    Canonical upsert mechanism: creates or updates game requirements in the database.
    """
    try:
        return agent_service.upsert_game(
            game=req.game,
            required_ram_gb=req.required_ram_gb,
            required_vram_gb=req.required_vram_gb,
            source_url=req.source_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/add")
def add_game(req: GameUpsertRequest, agent_service: PcAgentService = Depends(get_agent_service)):
    """
    Wrapper around upsert that fails with 409 Conflict if the game already exists in the catalog.
    """
    try:
        return agent_service.add_game(
            game=req.game,
            required_ram_gb=req.required_ram_gb,
            required_vram_gb=req.required_vram_gb,
            source_url=req.source_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update")
def update_game(req: GameUpsertRequest, agent_service: PcAgentService = Depends(get_agent_service)):
    """
    Wrapper around upsert that fails with 404 Not Found if the game does not exist in the catalog.
    """
    try:
        return agent_service.update_game(
            game=req.game,
            required_ram_gb=req.required_ram_gb,
            required_vram_gb=req.required_vram_gb,
            source_url=req.source_url,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
