import sys
from pathlib import Path

# Path bootstrap
API_DIR = Path(__file__).resolve().parent
BACKEND_DIR = API_DIR.parents[0]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.agent_service import PcAgentService

_agent_service_instance = None

def get_agent_service() -> PcAgentService:
    global _agent_service_instance
    if _agent_service_instance is None:
        _agent_service_instance = PcAgentService()
    return _agent_service_instance
