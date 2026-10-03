#!/usr/bin/env python3
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ksp_pc_builder_agent_bundle.data.common.io import load_json, save_json
from ksp_pc_builder_agent_bundle.data.common.paths import CatalogPaths

KNOWN_URLS_PATH = CatalogPaths.KNOWN_GAMES_URLS
TARGET_DOMAIN = "systemrequirementslab.com"
PRIMARY_MODEL = "qwen3.5:latest"  # Selected for strong JSON structured reasoning
FALLBACK_MODEL = "qwen2.5:7b"
OLLAMA_HOST = "http://localhost:11434"


def normalize_game_slug(name: str) -> str:
    """Creates a consistent game key for deduplication."""
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower())
    return " ".join(clean.split())


# ---------------------------------------------------------------------------
# Tier 1: Deterministic Search
# ---------------------------------------------------------------------------

def search_srl_url_deterministic(game_title: str) -> str | None:
    """Attempts standard DuckDuckGo scraping to find SRL URL."""
    query = f"site:{TARGET_DOMAIN}/cyri/requirements {game_title}"
    encoded_query = urllib.parse.quote_plus(query)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    try:
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode("utf-8")

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "uddg=" in href:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = parsed.get("uddg", [href])[0]

            if TARGET_DOMAIN in href and "/cyri/requirements/" in href:
                return href
    except Exception as e:
        print(f"[DETERMINISTIC WARN] Search failed for '{game_title}': {e}")

    return None


# ---------------------------------------------------------------------------
# Tier 2: Ollama Fallback Agent Management
# ---------------------------------------------------------------------------

class OllamaLifecycleManager:
    """Ensures Ollama is running during inference and stopped afterward if started by this script."""

    def __init__(self):
        self.started_by_us = False
        self.process = None

    def __enter__(self):
        if not self._is_ollama_running():
            print("[OLLAMA] Server not detected. Starting temporary Ollama instance...")
            self.process = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.started_by_us = True
            time.sleep(3)  # Wait for boot
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.started_by_us and self.process:
            print("[OLLAMA] Cleaning up temporary Ollama process...")
            self.process.terminate()
            self.process.wait()

    def _is_ollama_running(self) -> bool:
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as res:
                return res.status == 200
        except Exception:
            return False


def query_ollama_for_url(game_title: str) -> str | None:
    """Prompts Ollama to output valid JSON with expected game slug."""
    prompt = (
        f"Generate the exact SystemRequirementsLab URL slug path for the game '{game_title}'. "
        f"Return strictly JSON in format: {{\"url\": \"https://www.systemrequirementslab.com/cyri/requirements/GAME_SLUG/ID\"}}"
    )
    
    payload = json.dumps({
        "model": PRIMARY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json"
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = json.loads(res_data["message"]["content"])
            url = content.get("url", "")
            if TARGET_DOMAIN in url and "/cyri/requirements/" in url:
                return url
    except Exception as e:
        print(f"[OLLAMA ERROR] LLM lookup failed for '{game_title}': {e}")

    return None


# ---------------------------------------------------------------------------
# Main Normalization Routine
# ---------------------------------------------------------------------------

def update_known_games_urls() -> None:
    """Update known_games_url.json: dedupe slugs and resolve SRL URLs."""
    entries = load_json(KNOWN_URLS_PATH, [])
    if not entries:
        print(f"[WARN] No entries found in {KNOWN_URLS_PATH.name}")
        return

    # Deduplication map: slug -> entry dict
    dedup_map = {}
    items_to_resolve = []

    for entry in entries:
        game_title = entry.get("game", "")
        slug = normalize_game_slug(game_title)
        
        # Merge duplicates
        if slug not in dedup_map:
            dedup_map[slug] = entry
        else:
            # Keep entry if it already has a valid target URL
            if TARGET_DOMAIN in entry.get("url", "").lower():
                dedup_map[slug] = entry

        current_url = dedup_map[slug].get("url", "")
        if TARGET_DOMAIN not in current_url.lower():
            items_to_resolve.append((slug, game_title))

    if not items_to_resolve:
        print(f"[DONE] All {len(dedup_map)} games have valid {TARGET_DOMAIN} URLs.")
        save_json(KNOWN_URLS_PATH, list(dedup_map.values()))
        return

    print(f"[AGENT] Resolving {len(items_to_resolve)} non-standard game URLs...\n")
    unresolved_for_ollama = []

    # Step 1: Deterministic Pass
    for slug, game_title in items_to_resolve:
        print(f"[DETERMINISTIC] Searching for '{game_title}'...")
        srl_url = search_srl_url_deterministic(game_title)
        if srl_url:
            print(f" -> Found: {srl_url}\n")
            dedup_map[slug]["url"] = srl_url
        else:
            print(f" -> Failed deterministic search. Queuing for Ollama.\n")
            unresolved_for_ollama.append((slug, game_title))

    # Step 2: Ollama Fallback (if deterministic search misses items)
    if unresolved_for_ollama:
        print(f"[AGENT] Launching Ollama LLM fallback for {len(unresolved_for_ollama)} remaining entries...")
        with OllamaLifecycleManager():
            for slug, game_title in unresolved_for_ollama:
                print(f"[OLLAMA] Reasoning link for '{game_title}' using {PRIMARY_MODEL}...")
                srl_url = query_ollama_for_url(game_title)
                if srl_url:
                    print(f" -> Resolved via LLM: {srl_url}\n")
                    dedup_map[slug]["url"] = srl_url
                else:
                    print(f" -> Could not resolve '{game_title}'. Keeping existing entry.\n")

    # Step 3: Write deduplicated & normalized JSON
    final_list = list(dedup_map.values())
    save_json(KNOWN_URLS_PATH, final_list)
    print(f"[SUCCESS] Updated {KNOWN_URLS_PATH.name} ({len(final_list)} unique games total).")


if __name__ == "__main__":
    update_known_games_urls()