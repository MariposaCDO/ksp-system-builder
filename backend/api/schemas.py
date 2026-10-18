from pydantic import BaseModel, Field
from typing import List, Optional

class PromptRequest(BaseModel):
    prompt: str = Field(..., example="Build me a PC for Cyberpunk 2077 with 6000 ILS")

class ExplicitBuildRequest(BaseModel):
    games: List[str] = Field(..., example=["cyberpunk-2077"])
    budget: float = Field(..., example=6000.0)

class GameUpsertRequest(BaseModel):
    game: str = Field(..., example="cyberpunk-2077")
    required_ram_gb: int = Field(..., example=16, ge=1)
    required_vram_gb: int = Field(..., example=6, ge=0)
    source_url: Optional[str] = Field(default=None, example="https://www.systemrequirementslab.com/cyri/requirements/cyberpunk-2077")
