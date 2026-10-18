from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from services.agent_service import PcAgentService
from api.deps import get_agent_service

router = APIRouter(prefix="/api/v1/components", tags=["components"])

@router.get("/categories")
def get_component_categories(agent_service: PcAgentService = Depends(get_agent_service)):
    """Retrieve all available component categories in the parts database."""
    try:
        return agent_service.engine.catalog._db.get_categories()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cpu")
def get_all_cpu(max_price: Optional[float] = None, agent_service: PcAgentService = Depends(get_agent_service)):
    """Retrieve all CPU components, optionally filtered by max price."""
    try:
        return agent_service.get_components_by_category("cpu", max_price=max_price)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/gpu")
def get_all_gpu(max_price: Optional[float] = None, agent_service: PcAgentService = Depends(get_agent_service)):
    """Retrieve all GPU components, optionally filtered by max price."""
    try:
        return agent_service.get_components_by_category("gpu", max_price=max_price)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{component_category}")
def get_all_components_by_category(
    component_category: str,
    max_price: Optional[float] = None,
    agent_service: PcAgentService = Depends(get_agent_service),
):
    """
    Retrieve all components for any category (e.g., cpu, gpu, motherboard, ram, ssd, psu, case),
    optionally filtered by max price.
    """
    try:
        items = agent_service.get_components_by_category(component_category, max_price=max_price)
        return {
            "category": component_category,
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
