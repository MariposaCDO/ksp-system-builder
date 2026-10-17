"""
Ollama Service & Model Dependency Self-Healer
--------------------------------------------
Provides resilience, model health checks, automated downloading (pull),
pruning of unused/stale models, and graceful fallback when Ollama is offline.
"""

import json
import logging
import os
import sys
import requests
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("ollama_self_healer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class OllamaSelfHealer:
    """Manages Ollama connectivity, required model presence, and cleanup."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout: int = 10,
    ):
        raw_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.base_url = raw_url.rstrip("/")
        if self.base_url.endswith("/api"):
            self.base_url = self.base_url[:-4]
        self.primary_model = primary_model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.fallback_model = fallback_model or os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5-coder:7b")
        self.timeout = timeout

    def is_service_online(self) -> bool:
        """Check if Ollama server responds."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False

    def list_installed_models(self) -> List[str]:
        """Fetch list of all models currently available locally in Ollama."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name") or m.get("model")
                    if name:
                        models.append(name)
                return models
        except Exception as e:
            logger.warning(f"Failed to query installed Ollama models: {e}")
        return []

    def is_model_installed(self, model_name: str) -> bool:
        """Check if model (or normalized tag) is already pulled."""
        installed = self.list_installed_models()
        target = model_name if ":" in model_name else f"{model_name}:latest"
        for m in installed:
            m_norm = m if ":" in m else f"{m}:latest"
            if m_norm.lower() == target.lower():
                return True
        return False

    def pull_model(self, model_name: str, verbose: bool = True) -> bool:
        """Stream pull a model from Ollama library."""
        url = f"{self.base_url}/api/pull"
        logger.info(f"Self-healer: Pulling model '{model_name}' from Ollama...")
        try:
            with requests.post(url, json={"name": model_name, "stream": True}, stream=True, timeout=1800) as response:
                if response.status_code != 200:
                    logger.error(f"Failed to initiate pull for '{model_name}'. Status: {response.status_code}")
                    return False

                last_status = ""
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        status = chunk.get("status", "")
                        completed = chunk.get("completed", 0)
                        total = chunk.get("total", 0)

                        if verbose and (status != last_status or total > 0):
                            if total > 0:
                                pct = (completed / total) * 100
                                sys.stdout.write(f"\r  -> [{model_name}] {status}: {pct:.1f}% ({completed // (1024*1024)}MB / {total // (1024*1024)}MB)")
                                sys.stdout.flush()
                            else:
                                sys.stdout.write(f"\r  -> [{model_name}] {status}   ")
                                sys.stdout.flush()
                            last_status = status

                if verbose:
                    sys.stdout.write("\n")
                logger.info(f"Self-healer: Successfully pulled '{model_name}'.")
                return True
        except Exception as e:
            logger.error(f"Exception during pulling model '{model_name}': {e}")
            return False

    def remove_model(self, model_name: str) -> bool:
        """Delete a local model to free up storage / VRAM."""
        url = f"{self.base_url}/api/delete"
        logger.info(f"Self-healer: Removing model '{model_name}'...")
        try:
            r = requests.delete(url, json={"name": model_name}, timeout=self.timeout)
            if r.status_code == 200:
                logger.info(f"Self-healer: Removed '{model_name}'.")
                return True
            logger.warning(f"Could not remove '{model_name}', status: {r.status_code}")
            return False
        except Exception as e:
            logger.error(f"Exception removing '{model_name}': {e}")
            return False

    def prune_unused_models(self, keep_models: List[str]) -> List[str]:
        """
        Delete models not present in keep_models list.
        Useful for constrained environments or teardowns.
        """
        installed = self.list_installed_models()
        keep_normalized = {m if ":" in m else f"{m}:latest" for m in keep_models}
        removed = []

        for m in installed:
            m_norm = m if ":" in m else f"{m}:latest"
            if m_norm not in keep_normalized:
                if self.remove_model(m):
                    removed.append(m)

        return removed

    def heal_model_dependencies(self, auto_pull: bool = True) -> Tuple[bool, str]:
        """
        Ensures a working model is available.
        1. Checks Ollama service availability.
        2. Checks primary model. If absent and auto_pull=True, pulls it.
        3. If primary fails, attempts fallback model.
        Returns: (success: bool, active_model_name: str)
        """
        if not self.is_service_online():
            return False, "Ollama service is unreachable"

        # Check primary model
        if self.is_model_installed(self.primary_model):
            return True, self.primary_model

        if auto_pull:
            logger.info(f"Primary model '{self.primary_model}' missing. Initiating self-heal pull...")
            if self.pull_model(self.primary_model):
                return True, self.primary_model

        # Check fallback model
        logger.warning(f"Primary model '{self.primary_model}' unavailable. Checking fallback '{self.fallback_model}'...")
        if self.is_model_installed(self.fallback_model):
            return True, self.fallback_model

        if auto_pull and self.fallback_model:
            logger.info(f"Fallback model '{self.fallback_model}' missing. Initiating self-heal pull...")
            if self.pull_model(self.fallback_model):
                return True, self.fallback_model

        return False, "No models available or pull failed"
