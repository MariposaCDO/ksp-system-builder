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

    Handles:
    - Abbreviations vs full names (e.g. 'civ 4' -> 'Civilization IV')
    - Roman numerals (already canonicalized: iv->4, v->5 etc.)
    - Fallback to word variations if no direct match is found.

    Strategy:
    1. Search with original name; score all candidates.
    2. If best score is weak (< 2.0), retry with numeric-only suffix
       (strips abbreviation prefix, keeps the edition number) so the SRL
       search engine can find the full franchise title.
    3. Number-match bonus: if query and title share the same edition number,
       apply a strong bonus to prefer the edition-correct result.
    """
    def _score_candidates(candidates, target_tokens, target_str):
        def match_score(item: Dict[str, Any]) -> float:
            title_tokens = canonicalize_tokens(item["title"])
            title_str = " ".join(title_tokens)

            # Exact canonical token match
            if target_tokens == title_tokens or target_str == title_str:
                return 20.0

            score = SequenceMatcher(None, target_str, title_str).ratio() * 5.0
            target_set = set(target_tokens)
            title_set = set(title_tokens)

            # Subset match (all query tokens appear in title)
            if target_set and target_set.issubset(title_set):
                score += 10.0

            # Edition number match bonus — same digit edition = strong signal
            target_nums = set(re.findall(r"\b\d+\b", target_str))
            title_nums = set(re.findall(r"\b\d+\b", title_str))
            if target_nums and title_nums:
                if target_nums == title_nums:
                    score += 8.0  # same edition, boost
                elif not target_nums.isdisjoint(title_nums):
                    score += 3.0  # partial overlap
                else:
                    score -= 15.0  # edition mismatch, penalize

            return score
        return max(candidates, key=match_score), match_score(max(candidates, key=match_score))

    candidates = search_srl_games(game_name, timeout=timeout)

    # Fallback 1: try truncated name (first 3 words)
    if not candidates:
        clean_target = re.sub(r'[^a-zA-Z0-9\s]', ' ', game_name).strip()
        words = clean_target.split()
        if len(words) > 2:
            shortened = " ".join(words[:3])
            candidates = search_srl_games(shortened, timeout=timeout)

    # Fallback 2: try searching only the numeric part (edition number) if present
    # e.g. "civ 4" -> "4" won't help, but "civilization 4" prefix removal won't either.
    # Instead try just the non-numeric part as a broader search term.
    if not candidates:
        # Extract only the alphabetic portion (e.g. "civ" from "civ 4")
        alpha_part = re.sub(r'\d+', '', game_name).strip()
        if alpha_part and alpha_part != game_name.strip():
            candidates = search_srl_games(alpha_part, timeout=timeout)

    if not candidates:
        return None

    target_tokens = canonicalize_tokens(game_name)
    target_str = " ".join(target_tokens)

    best = max(candidates, key=lambda item: _score_candidates([item], target_tokens, target_str)[1])

    # If the best match has a weak score, try a broader search with alphabetic prefix only
    # to catch cases like "civ 4" not matching "Civilization IV" well enough.
    best_score = _score_candidates([best], target_tokens, target_str)[1]
    if best_score < 3.0:
        alpha_part = re.sub(r'\d+', '', game_name).strip()
        if alpha_part and alpha_part != game_name.strip():
            broader_candidates = search_srl_games(alpha_part, timeout=timeout)
            if broader_candidates:
                all_candidates = candidates + [c for c in broader_candidates if c not in candidates]
                best = max(all_candidates, key=lambda item: _score_candidates([item], target_tokens, target_str)[1])

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
