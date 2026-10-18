from fastapi import APIRouter, HTTPException, Depends
from services.agent_service import PcAgentService
from api.schemas import PromptRequest, ExplicitBuildRequest
from api.deps import get_agent_service

router = APIRouter(prefix="/api/v1/build", tags=["build"])

def _check_missing_games(result: dict) -> None:
    reqs = result.get("requirements", {})
    unrecognized = reqs.get("unrecognized_games", [])
    if unrecognized:
        missing_str = ", ".join(unrecognized)
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Game(s) missing from catalog: {missing_str}",
                "unrecognized_games": unrecognized,
                "hint": (
                    f"To add missing game requirements, send a POST request to '/api/v1/games/upsert' "
                    f"or '/api/v1/games/add' with payload: "
                    f'{{"game": "{unrecognized[0]}", "required_ram_gb": 16, "required_vram_gb": 6, "source_url": "optional_url"}}'
                ),
            },
        )

@router.post("/prompt")
def build_from_prompt(req: PromptRequest, agent_service: PcAgentService = Depends(get_agent_service)):
    try:
        result = agent_service.process_prompt(req.prompt)
        _check_missing_games(result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/explicit")
def build_explicit(req: ExplicitBuildRequest, agent_service: PcAgentService = Depends(get_agent_service)):
    try:
        result = agent_service.process_explicit(req.games, req.budget)
        _check_missing_games(result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
