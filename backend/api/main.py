from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import sys
from pathlib import Path

# Path bootstrap
API_DIR = Path(__file__).resolve().parent
BACKEND_DIR = API_DIR.parents[0]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.agent_service import PcAgentService
from ksp_pc_builder_agent_bundle import run_preflight_checks

app = FastAPI(title="KSP System Builder API", version="1.0.0")
agent_service = PcAgentService()

class PromptRequest(BaseModel):
    prompt: str = Field(..., example="Build me a PC for Cyberpunk 2077 with 6000 ILS")

class ExplicitBuildRequest(BaseModel):
    games: List[str] = Field(..., example=["cyberpunk-2077"])
    budget: float = Field(..., example=6000.0)

@app.on_event("startup")
def startup_event():
    ok, stale_files = run_preflight_checks(stale_mode="ignore")
    if not ok:
        print("[WARNING] Preflight checks encountered errors during startup.")

@app.post("/api/v1/build/prompt")
def build_from_prompt(req: PromptRequest):
    try:
        result = agent_service.process_prompt(req.prompt)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/build/explicit")
def build_explicit(req: ExplicitBuildRequest):
    try:
        result = agent_service.process_explicit(req.games, req.budget)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))