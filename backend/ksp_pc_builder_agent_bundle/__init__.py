"""
KSP PC Builder Agent Bundle
===========================
Self-contained agent bundle providing hardware recommendations, 
compatibility verification, and system assembly logic based on KSP parts catalog data.
"""

from .ksp_pc_builder_agent_engine import KspPcBuilderAgentEngine
from .ksp_pc_builder_config import Config
from .ksp_pc_builder_preflight import run_preflight_checks, check_games_in_catalog

__version__ = "1.0.0"
__all__ = ["KspPcBuilderAgentEngine", "Config", "run_preflight_checks", "check_games_in_catalog"]