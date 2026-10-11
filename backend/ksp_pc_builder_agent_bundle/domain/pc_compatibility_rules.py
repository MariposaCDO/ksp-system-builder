"""
PC Compatibility Rules — Tag/Category Engine.

Validates physical and technical compatibility across selected PC parts
using deterministic tag/category ID intersection from the catalog,
with secondary string/name fallback checks when DB tags are incomplete.
"""

import logging
import re
from typing import Dict, Any, Tuple, Optional, Set

logger = logging.getLogger("KspAgentEngine")


# ---------------------------------------------------------------------------
# Tag-ID constants (deterministic from parts_db.json schema)
# ---------------------------------------------------------------------------

# Category 24 — CPU Socket
SOCKET_TAG_CAT = "24"
SOCKET_TAG_IDS: Dict[str, str] = {
    "3951":  "AM4",
    "40186": "AM5",
    "29757": "LGA1700",
    "63202": "LGA1851",
}

# Category 27 — Memory Standard
MEMORY_TAG_CAT = "27"
MEMORY_TAG_IDS: Dict[str, str] = {
    "127":   "DDR3",
    "2100":  "DDR4",
    "29758": "DDR5",
}

# Category 28 — Form Factor
FORM_FACTOR_TAG_CAT = "28"
_ATX_EXCLUSIVE_TAGS: Set[str] = {"121"}   # ATX
_SMALL_CASE_TAGS: Set[str] = {"123", "124"}  # Micro-ATX, Mini-ITX


# ---------------------------------------------------------------------------
# Helpers & Fallback Parsers
# ---------------------------------------------------------------------------

def _tag_set(item: Dict[str, Any], cat: str) -> Set[str]:
    """Return the set of tag values for a given category on an item."""
    raw = item.get("tags", {})
    if not isinstance(raw, dict):
        return set()
    return set(raw.get(cat, []))


def _extract_socket_from_text(text: str) -> Optional[str]:
    """Fallback socket parser for names/descriptions when tags are missing."""
    t = text.upper()
    if "AM5" in t:
        return "AM5"
    if "AM4" in t:
        return "AM4"
    if "LGA1851" in t or "1851" in t or "ULTRA" in t:
        return "LGA1851"
    if "LGA1700" in t or "1700" in t:
        return "LGA1700"
    return None


def _extract_ram_std_from_text(text: str) -> Optional[str]:
    """Fallback RAM standard parser for names/descriptions when tags are missing."""
    t = text.upper()
    if "DDR5" in t:
        return "DDR5"
    if "DDR4" in t:
        return "DDR4"
    if "DDR3" in t:
        return "DDR3"
    return None


_PSU_WATT_RE = re.compile(r"\b(\d{3,4})\s*w\b", re.I)
_GPU_LEN_RE  = re.compile(r"(\d{3})\s*mm")


def _extract_psu_wattage(name: str) -> Optional[int]:
    m = _PSU_WATT_RE.search(name)
    if m:
        return int(m.group(1))
    m2 = re.search(r"\b[a-zA-Z]+[_-]?(\d{3,4})\b", name)
    if m2:
        val = int(m2.group(1))
        if 300 <= val <= 1600:
            return val
    return None


def _estimate_min_wattage(current_build: Dict[str, Any]) -> int:
    est_cpu = 65
    est_gpu = 75

    if "cpu" in current_build:
        n = current_build["cpu"].get("name", "").lower()
        if any(k in n for k in ["x3d", "i9", "ryzen 9", "ultra 9"]):
            est_cpu = 125
        elif any(k in n for k in ["ryzen 7", "i7", "ultra 7"]):
            est_cpu = 105

    if "gpu" in current_build:
        n = current_build["gpu"].get("name", "").lower()
        if any(k in n for k in ["9060 xt", "3060", "4060", "7600"]):
            est_gpu = 180
        elif any(k in n for k in ["5070", "5080", "5090", "9070", "4070", "4080"]):
            est_gpu = 280

    return int((est_cpu + est_gpu + 50) * 1.3)


def _gpu_length_from_name(name: str) -> Optional[int]:
    m = _GPU_LEN_RE.search(name.lower())
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Internal Check Functions
# ---------------------------------------------------------------------------

def _get_item_sockets(item: Dict[str, Any]) -> Set[str]:
    """Get resolved socket names from tags or text fallback."""
    raw_tags = _tag_set(item, SOCKET_TAG_CAT)
    resolved = {SOCKET_TAG_IDS[t] for t in raw_tags if t in SOCKET_TAG_IDS}
    
    if not resolved:
        text = f"{item.get('name', '')} {item.get('description', '')}"
        fallback = _extract_socket_from_text(text)
        if fallback:
            resolved.add(fallback)
    return resolved


def _get_item_ram_standards(item: Dict[str, Any]) -> Set[str]:
    """Get resolved RAM standards from tags or text fallback."""
    raw_tags = _tag_set(item, MEMORY_TAG_CAT)
    resolved = {MEMORY_TAG_IDS[t] for t in raw_tags if t in MEMORY_TAG_IDS}

    if not resolved:
        text = f"{item.get('name', '')} {item.get('description', '')}"
        fallback = _extract_ram_std_from_text(text)
        if fallback:
            resolved.add(fallback)
    return resolved


def _check_socket(
    cpu: Dict[str, Any], motherboard: Dict[str, Any]
) -> Tuple[bool, str]:
    """Verify CPU socket intersects with motherboard socket."""
    cpu_sockets = _get_item_sockets(cpu)
    mb_sockets  = _get_item_sockets(motherboard)

    if not cpu_sockets or not mb_sockets:
        # Fallback to true only if no socket data can be inferred
        return True, "OK"

    if cpu_sockets & mb_sockets:
        return True, "OK"

    return False, f"Socket Mismatch: CPU ({', '.join(cpu_sockets)}) vs Motherboard ({', '.join(mb_sockets)})"


def _check_memory(
    ram: Dict[str, Any], motherboard: Dict[str, Any]
) -> Tuple[bool, str]:
    """Verify RAM standard intersects with motherboard memory standard."""
    ram_std = _get_item_ram_standards(ram)
    mb_std  = _get_item_ram_standards(motherboard)

    if not ram_std or not mb_std:
        return True, "OK"

    if ram_std & mb_std:
        return True, "OK"

    return False, f"RAM Mismatch: RAM standard ({', '.join(ram_std)}) vs Motherboard ({', '.join(mb_std)})"


def _check_form_factor(
    motherboard: Dict[str, Any], case: Dict[str, Any]
) -> Tuple[bool, str]:
    mb_ff   = _tag_set(motherboard, FORM_FACTOR_TAG_CAT)
    case_ff = _tag_set(case, FORM_FACTOR_TAG_CAT)

    mb_is_atx_only = bool(mb_ff & _ATX_EXCLUSIVE_TAGS) and not (mb_ff & _SMALL_CASE_TAGS)
    case_is_small  = bool(case_ff & _SMALL_CASE_TAGS)

    if mb_is_atx_only and case_is_small:
        return False, "Form Factor Mismatch: ATX Motherboard cannot fit in a smaller case"

    return True, "OK"


# ---------------------------------------------------------------------------
# Public Rule Class
# ---------------------------------------------------------------------------

class PCCompatibilityRules:
    """
    Validates physical and technical compatibility across selected PC parts.
    Uses deterministic tag category IDs with secondary text fallbacks.
    """

    def is_compatible(
        self,
        category: str,
        candidate: Dict[str, Any],
        current_build: Dict[str, Any],
    ) -> Tuple[bool, str]:

        # -- 1. CPU <-> Motherboard (socket) --
        if category == "motherboard" and "cpu" in current_build:
            ok, msg = _check_socket(current_build["cpu"], candidate)
            if not ok:
                return False, msg

        if category == "cpu" and "motherboard" in current_build:
            ok, msg = _check_socket(candidate, current_build["motherboard"])
            if not ok:
                return False, msg

        # -- 2. RAM <-> Motherboard (memory standard) --
        if category == "ram" and "motherboard" in current_build:
            ok, msg = _check_memory(candidate, current_build["motherboard"])
            if not ok:
                return False, msg

        if category == "motherboard" and "ram" in current_build:
            ok, msg = _check_memory(current_build["ram"], candidate)
            if not ok:
                return False, msg

        # -- 3. Motherboard <-> Case (form factor) --
        if category == "case" and "motherboard" in current_build:
            ok, msg = _check_form_factor(current_build["motherboard"], candidate)
            if not ok:
                return False, msg

        if category == "motherboard" and "case" in current_build:
            ok, msg = _check_form_factor(candidate, current_build["case"])
            if not ok:
                return False, msg

        # -- 4. GPU Physical Clearance --
        if category == "gpu" and "case" in current_build:
            gpu_len  = _gpu_length_from_name(candidate.get("name", ""))
            case_len = _gpu_length_from_name(current_build["case"].get("name", ""))
            if gpu_len and case_len and gpu_len > case_len:
                return False, f"Physical Clearance Mismatch: GPU ({gpu_len}mm) exceeds Case ({case_len}mm)"

        if category == "case" and "gpu" in current_build:
            gpu_len  = _gpu_length_from_name(current_build["gpu"].get("name", ""))
            case_len = _gpu_length_from_name(candidate.get("name", ""))
            if gpu_len and case_len and gpu_len > case_len:
                return False, f"Physical Clearance Mismatch: GPU ({gpu_len}mm) exceeds Case ({case_len}mm)"

        # -- 5. PSU Minimum Wattage --
        if category == "psu":
            psu_watts = _extract_psu_wattage(candidate.get("name", ""))
            if psu_watts:
                min_watts = _estimate_min_wattage(current_build)
                if psu_watts < min_watts:
                    return False, f"Power Insufficient: PSU ({psu_watts}W) below system minimum ({min_watts}W)"

        return True, "OK"