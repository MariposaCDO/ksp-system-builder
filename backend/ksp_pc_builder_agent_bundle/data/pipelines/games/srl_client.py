"""
SystemRequirementsLab (CYRI) Client & Requirement Parser.

Provides deterministic search and spec extraction using SRL's searchterm endpoint:
  https://www.systemrequirementslab.com/cyri/?handler=searchterm&term={game_name}
and requirement pages:
  https://www.systemrequirementslab.com/cyri/requirements/{uri_mask}/{id}
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SrlClient")

SRL_DOMAIN = "systemrequirementslab.com"
SRL_BASE_URL = "https://www.systemrequirementslab.com"
SRL_SEARCH_URL = f"{SRL_BASE_URL}/cyri/?handler=searchterm&term="
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)

ROMAN_TO_DEC = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"
}


def canonicalize_tokens(text: str) -> List[str]:
    """Normalize text into canonical tokens, translating Roman numerals to arabic digits."""
    text = text.lower().replace("&", "and")
    tokens = re.findall(r"[a-zA-Z0-9]+", text)
    return [ROMAN_TO_DEC.get(t, t) for t in tokens if t not in ("the", "edition", "hd", "game")]


def search_srl_games(game_name: str, timeout: int = 10) -> List[Dict[str, Any]]:
    """
    Query the SRL searchterm endpoint for a given game name.
    Returns a list of dicts with title, id, uri_mask, and canonical url.
    """
    if not game_name or not game_name.strip():
        return []

    encoded = urllib.parse.quote_plus(game_name.strip())
    req_url = f"{SRL_SEARCH_URL}{encoded}"
    headers = {"User-Agent": USER_AGENT}

    try:
        req = urllib.request.Request(req_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        items = data.get("items", [])
        results = []
        for item in items:
            item_id = item.get("id")
            uri_mask = item.get("uri_Mask", "")
            title = item.get("text", "")
            url = f"{SRL_BASE_URL}/cyri/requirements/{uri_mask}/{item_id}" if uri_mask and item_id else ""
            results.append({
                "id": item_id,
                "title": title,
                "uri_mask": uri_mask,
                "url": url,
            })
        return results
    except Exception as e:
        logger.warning("[SRL] Failed to search for '%s': %s", game_name, e)
        return []


def resolve_best_srl_game(game_name: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """
    Search SRL for game_name and find the best match using title similarity.
    Fallback to word variations (e.g. without trailing numbers or common tokens) if no direct match.
    """
    candidates = search_srl_games(game_name, timeout=timeout)
    if not candidates:
        clean_target = re.sub(r'[^a-zA-Z0-9\s]', ' ', game_name).strip()
        words = clean_target.split()
        if len(words) > 2:
            shortened = " ".join(words[:3])
            candidates = search_srl_games(shortened, timeout=timeout)

    if not candidates:
        return None

    target_tokens = canonicalize_tokens(game_name)
    target_str = " ".join(target_tokens)

    def match_score(item: Dict[str, Any]) -> float:
        title_tokens = canonicalize_tokens(item["title"])
        title_str = " ".join(title_tokens)

        # Exact canonical token match
        if target_tokens == title_tokens or target_str == title_str:
            return 20.0

        # Exact substring or subset
        score = SequenceMatcher(None, target_str, title_str).ratio() * 5.0
        target_set = set(target_tokens)
        title_set = set(title_tokens)
        if target_set and target_set.issubset(title_set):
            score += 10.0

        # Penalize edition mismatch if numbers differ (e.g. 3 vs 5)
        target_nums = set(re.findall(r"\b\d+\b", target_str))
        title_nums = set(re.findall(r"\b\d+\b", title_str))
        if target_nums and title_nums and target_nums != title_nums:
            score -= 15.0

        return score

    best = max(candidates, key=match_score)
    return best


def parse_specs_from_srl_html(html_text: str) -> Dict[str, Any]:
    """
    Parse requirements from SRL HTML page.
    Extracts minimum and recommended specifications.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")
    tiers: Dict[str, Dict[str, Any]] = {}

    # Locate ULs that contain RAM/CPU/VIDEO CARD specs
    spec_uls = [
        ul for ul in soup.find_all("ul")
        if any("RAM" in li.get_text() for li in ul.find_all("li"))
    ]

    for ul in spec_uls:
        prev_headings = ul.find_all_previous(["h1", "h2", "h3", "h4", "h5", "strong"])
        heading_text = " ".join([h.get_text(strip=True).lower() for h in prev_headings[:2]])
        tier_key = "recommended" if "recommended" in heading_text else "minimum"

        tier_data: Dict[str, str] = {}
        for li in ul.find_all("li"):
            text = li.get_text(" ", strip=True)
            if ":" in text:
                k, v = text.split(":", 1)
                tier_data[k.strip().upper()] = v.strip()

        # Parse RAM (GB)
        ram_gb = 0
        if "RAM" in tier_data:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB)", tier_data["RAM"], re.I)
            if m:
                val = float(m.group(1))
                ram_gb = int(round(val)) if m.group(2).upper() == "GB" else max(1, int(round(val / 1024.0)))

        # Parse VRAM (GB)
        vram_gb = 0
        vram_raw = tier_data.get("DEDICATED VIDEO RAM") or tier_data.get("VIDEO CARD", "")
        m_vram = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB)", vram_raw, re.I)
        if m_vram:
            val = float(m_vram.group(1))
            vram_gb = int(round(val)) if m_vram.group(2).upper() == "GB" else max(1, int(round(val / 1024.0)))

        tiers[tier_key] = {
            "ram_gb": max(1, ram_gb) if ram_gb else (8 if tier_key == "minimum" else 16),
            "vram_gb": max(1, vram_gb) if vram_gb else (2 if tier_key == "minimum" else 6),
            "cpu_hint": tier_data.get("CPU", ""),
            "gpu_hint": tier_data.get("VIDEO CARD", ""),
            "storage_gb": tier_data.get("FREE DISK SPACE", ""),
            "os": tier_data.get("OS", ""),
            "target": "1080p / 30 FPS" if tier_key == "minimum" else "1080p / 60 FPS",
        }

    # Ensure minimum tier is present
    if "minimum" not in tiers:
        tiers["minimum"] = {
            "ram_gb": 8,
            "vram_gb": 2,
            "target": "1080p / 30 FPS",
        }

    req_ram = tiers["minimum"]["ram_gb"]
    req_vram = tiers["minimum"]["vram_gb"]

    return {
        "required_ram_gb": req_ram,
        "required_vram_gb": req_vram,
        "tiers": tiers,
    }


def fetch_srl_game_specs(url: str, timeout: int = 10) -> Dict[str, Any]:
    """Fetch and parse specs from a given SRL requirements URL."""
    headers = {"User-Agent": USER_AGENT}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    return parse_specs_from_srl_html(html)
