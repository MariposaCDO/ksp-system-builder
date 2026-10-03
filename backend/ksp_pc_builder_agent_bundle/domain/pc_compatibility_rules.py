import logging
import re
from pathlib import Path
import json
from typing import Dict, Any, Tuple, Optional

from ksp_pc_builder_agent_bundle.ksp_pc_builder_config import Config
from ksp_pc_builder_agent_bundle.data.common.db import CatalogDB

logger = logging.getLogger("KspAgentEngine")


class PCCompatibilityRules:
    """Validates physical and technical compatibility across selected PC parts."""

    CATEGORY_MAP = {
        "cpu":        "cpus",
        "motherboard": "motherboards",
        "ram":        "ram",
        "case":       "cases",
        "gpu":        "video-card",
        "psu":        "power-supply",
    }

    # Maps microarchitecture from itemized_parts_specs.json to CPU Sockets
    MICROARCH_TO_SOCKET = {
        "Zen":                  "AM4",
        "Zen+":                 "AM4",
        "Zen 2":                "AM4",
        "Zen 3":                "AM4",
        "Zen 4":                "AM5",
        "Zen 5":                "AM5",
        "Coffee Lake":          "LGA1151",
        "Coffee Lake Refresh":  "LGA1151",
        "Comet Lake":           "LGA1200",
        "Rocket Lake":          "LGA1200",
        "Alder Lake":           "LGA1700",
        "Raptor Lake":          "LGA1700",
        "Raptor Lake Refresh":  "LGA1700",
        "Arrow Lake":           "LGA1851",
    }

    def __init__(self, specs_db: Optional[CatalogDB] = None):
        # Accept an injected CatalogDB (e.g. for testing) or create a fresh one.
        self._db = specs_db if specs_db is not None else CatalogDB()

    def extract_specs(self, category: str, part_name: str) -> Dict[str, Any]:
        """Extracts technical specs (socket, ram_type, form_factor) using the specs DB, microarchitecture maps, and regex."""
        name_lower = part_name.lower()
        name_clean = name_lower.replace(" ", "")
        extracted = {"socket": None, "ram_type": None, "form_factor": None}

        # Normalize category to match specs DB key (e.g. 'cpu' → 'cpus')
        db_category = self.CATEGORY_MAP.get(category, category)

        # 1. Primary Check: Indexed lookup via CatalogDB (replaces full-table JSON scan)
        matched_item = self._db.get_specs(db_category, part_name)
        if matched_item:
            extracted["socket"]      = matched_item.get("socket")
            extracted["ram_type"]    = matched_item.get("memory_type") or matched_item.get("ram_type")
            extracted["form_factor"] = matched_item.get("form_factor")

        # 2. Derive Socket from CPU Microarchitecture if missing in DB
        if matched_item and not extracted["socket"]:
            microarch = matched_item.get("microarchitecture")
            if microarch in self.MICROARCH_TO_SOCKET:
                extracted["socket"] = self.MICROARCH_TO_SOCKET[microarch]

        # 3. Dynamic Regex Check for explicit Socket / RAM
        if not extracted["socket"]:
            socket_match = re.search(r"\b(am[45]|str\d+|lga\d+)\b", name_lower)
            if socket_match:
                extracted["socket"] = socket_match.group(1).upper()

        if not extracted["ram_type"]:
            ram_match = re.search(r"\bddr[345]\b", name_lower)
            if ram_match:
                extracted["ram_type"] = ram_match.group(0).upper()

        # 4. Known Chipset Mapping (Fills in missing Socket & RAM Type for Motherboards)
        if not extracted["socket"] or not extracted["ram_type"]:
            # AMD AM4 Chipsets (Strictly DDR4)
            if any(c in name_clean for c in ["b550", "a520", "x570", "b450", "a320", "x470"]):
                extracted["socket"] = extracted["socket"] or "AM4"
                extracted["ram_type"] = extracted["ram_type"] or "DDR4"
            # AMD AM5 Chipsets (Strictly DDR5)
            elif any(c in name_clean for c in ["b650", "a620", "x670", "b850", "x870"]):
                extracted["socket"] = extracted["socket"] or "AM5"
                extracted["ram_type"] = extracted["ram_type"] or "DDR5"
            # Intel LGA1200 Chipsets (Strictly DDR4)
            elif any(c in name_clean for c in ["z590", "b560", "h510", "z490", "b460", "h410"]):
                extracted["socket"] = extracted["socket"] or "LGA1200"
                extracted["ram_type"] = extracted["ram_type"] or "DDR4"
            # Intel LGA1700 Chipsets (Supports DDR4 or DDR5 - ram_type left None if not explicit)
            elif any(c in name_clean for c in ["z790", "b760", "h610", "z690", "b660", "h670"]):
                extracted["socket"] = extracted["socket"] or "LGA1700"
            # Intel LGA1851 Chipsets (Strictly DDR5)
            elif any(c in name_clean for c in ["z890", "b860", "h810"]):
                extracted["socket"] = extracted["socket"] or "LGA1851"
                extracted["ram_type"] = extracted["ram_type"] or "DDR5"

        # 5. Fallback Socket-to-RAM Deduction strictly for non-ambiguous single-gen sockets
        if extracted["socket"] and not extracted["ram_type"]:
            if extracted["socket"] in ["AM4", "LGA1200", "LGA1151"]:
                extracted["ram_type"] = "DDR4"
            elif extracted["socket"] in ["AM5", "LGA1851"]:
                extracted["ram_type"] = "DDR5"

        # 6. Form Factor Resolution (Handles motherboard 'M' suffix like B550M)
        if not extracted["form_factor"]:
            if any(k in name_clean for k in ["micro-atx", "m-atx", "matx"]) or re.search(r"[abx]\d{3}m\b", name_clean):
                extracted["form_factor"] = "Micro-ATX"
            elif any(k in name_clean for k in ["mini-itx", "itx"]):
                extracted["form_factor"] = "Mini-ITX"
            elif "atx" in name_clean:
                extracted["form_factor"] = "ATX"

        return extracted

    def is_compatible(self, category: str, candidate: Dict[str, Any], current_build: Dict[str, Any]) -> Tuple[bool, str]:
        """Validates if candidate part physically works with already selected parts using fail-closed checks."""
        cand_name = candidate.get("name", "")
        cand_specs = self.extract_specs(category, cand_name)

        # 1. CPU vs Motherboard (Socket Check)
        if category == "motherboard" and "cpu" in current_build:
            cpu_name = current_build["cpu"].get("name", "")
            cpu_specs = self.extract_specs("cpu", cpu_name)
            
            if not cpu_specs["socket"] or not cand_specs["socket"]:
                return False, f"Uncertain Compatibility: Could not extract socket for CPU ({cpu_specs['socket']}) or Motherboard ({cand_specs['socket']})"
            
            if cpu_specs["socket"] != cand_specs["socket"]:
                return False, f"Socket Mismatch: CPU ({cpu_specs['socket']}) vs Motherboard ({cand_specs['socket']})"

        if category == "cpu" and "motherboard" in current_build:
            mb_name = current_build["motherboard"].get("name", "")
            mb_specs = self.extract_specs("motherboard", mb_name)
            
            if not mb_specs["socket"] or not cand_specs["socket"]:
                return False, f"Uncertain Compatibility: Could not extract socket for Motherboard ({mb_specs['socket']}) or CPU ({cand_specs['socket']})"
            
            if mb_specs["socket"] != cand_specs["socket"]:
                return False, f"Socket Mismatch: Motherboard ({mb_specs['socket']}) vs CPU ({cand_specs['socket']})"

        # 2. Motherboard vs RAM (DDR Generation Check)
        if category == "ram" and "motherboard" in current_build:
            mb_name = current_build["motherboard"].get("name", "")
            mb_specs = self.extract_specs("motherboard", mb_name)
            
            if not mb_specs["ram_type"] or not cand_specs["ram_type"]:
                return False, f"Uncertain Compatibility: Could not extract RAM type for Motherboard ({mb_specs['ram_type']}) or RAM ({cand_specs['ram_type']})"
            
            if mb_specs["ram_type"] != cand_specs["ram_type"]:
                return False, f"RAM Mismatch: Motherboard requires {mb_specs['ram_type']}, but RAM is {cand_specs['ram_type']}"

        if category == "motherboard" and "ram" in current_build:
            ram_name = current_build["ram"].get("name", "")
            ram_specs = self.extract_specs("ram", ram_name)
            
            if not ram_specs["ram_type"] or not cand_specs["ram_type"]:
                return False, f"Uncertain Compatibility: Could not extract RAM type for RAM ({ram_specs['ram_type']}) or Motherboard ({cand_specs['ram_type']})"
            
            if ram_specs["ram_type"] != cand_specs["ram_type"]:
                return False, f"RAM Mismatch: RAM is {ram_specs['ram_type']}, but Motherboard requires {cand_specs['ram_type']}"

        # 3. Motherboard vs Case (Form Factor Check)
        if category == "case" and "motherboard" in current_build:
            mb_specs = self.extract_specs("motherboard", current_build["motherboard"].get("name", ""))
            if mb_specs["form_factor"] == "ATX" and cand_specs["form_factor"] in ["Micro-ATX", "Mini-ITX"]:
                return False, f"Form Factor Mismatch: ATX Motherboard cannot fit in a {cand_specs['form_factor']} Case"

        if category == "motherboard" and "case" in current_build:
            case_specs = self.extract_specs("case", current_build["case"].get("name", ""))
            if cand_specs["form_factor"] == "ATX" and case_specs["form_factor"] in ["Micro-ATX", "Mini-ITX"]:
                return False, f"Form Factor Mismatch: ATX Motherboard cannot fit in a {case_specs['form_factor']} Case"

        # 4. GPU vs Case Physical Length Clearance Check
        if (category == "case" and "gpu" in current_build) or (category == "gpu" and "case" in current_build):
            gpu_name = candidate.get("name", "") if category == "gpu" else current_build["gpu"].get("name", "")
            case_name = candidate.get("name", "") if category == "case" else current_build["case"].get("name", "")
            
            gpu_len = self._get_gpu_length(gpu_name)
            max_len = self._get_case_max_gpu_len(case_name)
            if gpu_len and max_len and gpu_len > max_len:
                return False, f"Physical Clearance Mismatch: GPU length ({gpu_len}mm) exceeds case limit ({max_len}mm)"

        # 5. PSU Wattage Headroom Check vs Selected Components (CPU & GPU)
        if category == "psu":
            psu_watts = self._extract_psu_wattage(candidate.get("name", ""))
            if psu_watts:
                min_watts = self._estimate_min_wattage(current_build)
                if psu_watts < min_watts:
                    return False, f"Power Insufficient: PSU wattage ({psu_watts}W) below system minimum requirement ({min_watts}W)"

        # 6. GPU + CPU iGPU/APU Advisory (non-blocking warning)
        if category == "gpu" and "cpu" in current_build:
            cpu_name_lower = current_build["cpu"].get("name", "").lower()
            igpu_signals = [
                "with radeon graphics",   # AMD APU label (e.g. Ryzen 5 5600G with Radeon Graphics)
                "with graphics",          # generic iGPU suffix
                "igpu",
                "apu",
                "integrated",
            ]
            if any(sig in cpu_name_lower for sig in igpu_signals):
                logger.warning(
                    f"[ADVISORY] CPU '{current_build['cpu'].get('name')}' appears to be an APU "
                    f"with integrated graphics. Adding discrete GPU '{cand_name}' is valid but "
                    f"ensure the iGPU is disabled in BIOS for optimal performance."
                )

        return True, "OK"

    def _get_gpu_length(self, gpu_name: str) -> Optional[int]:
        """Extract GPU length in mm from name or specs DB."""
        name_lower = gpu_name.lower()
        # Direct regex in part name (e.g. 280mm)
        m = re.search(r"(\d{3})\s*mm", name_lower)
        if m:
            return int(m.group(1))

        # Model keyword lookup in specs DB
        gpu_specs_rows = self._db._conn.execute("SELECT raw_json FROM specs WHERE db_category='gpus'").fetchall()
        model_m = re.search(r"\b(rtx\s*\d{4}|gtx\s*\d{3,4}|gt\s*\d{3,4}|rx\s*\d{4}(?:\s*xt)?|arc\s*a\d{3})\b", name_lower)
        if model_m:
            model_str = model_m.group(1).replace(" ", "")
            for r in gpu_specs_rows:
                s_data = json.loads(r["raw_json"])
                if model_str in s_data.get("name", "").lower().replace(" ", "") and s_data.get("length"):
                    return int(s_data["length"])

        # Known model defaults fallback
        if "9060 xt" in name_lower or "gaming oc" in name_lower:
            return 281
        if "5080" in name_lower or "5090" in name_lower or "9070" in name_lower:
            return 300

        return None

    def _get_case_max_gpu_len(self, case_name: str) -> Optional[int]:
        """Extract max GPU clearance length in mm for a case."""
        name_lower = case_name.lower()
        if "vcx10m" in name_lower:
            return 260
        if "vx310" in name_lower or "vx320" in name_lower:
            return 350
        if "ax20" in name_lower or "ax26" in name_lower or "ax27" in name_lower:
            return 310

        m = re.search(r"gpu\s*(?:up to|max|len|length)?\s*(\d{3})\s*mm", name_lower)
        if m:
            return int(m.group(1))

        return None

    def _extract_psu_wattage(self, psu_name: str) -> Optional[int]:
        """Extract PSU wattage from part name (e.g. 550W, B650, 750W)."""
        m = re.search(r"\b(\d{3,4})\s*w\b", psu_name, re.I)
        if m:
            return int(m.group(1))
        m2 = re.search(r"\b[a-zA-Z]+[_-]?(\d{3,4})\b", psu_name)
        if m2:
            val = int(m2.group(1))
            if 300 <= val <= 1600:
                return val
        return None

    def _estimate_min_wattage(self, current_build: Dict[str, Any]) -> int:
        """Estimate minimum system PSU wattage required based on CPU & GPU."""
        est_cpu = 65
        est_gpu = 75

        if "cpu" in current_build:
            cpu_name = current_build["cpu"].get("name", "").lower()
            if "x3d" in cpu_name or "i9" in cpu_name or "ryzen 9" in cpu_name or "ultra 9" in cpu_name:
                est_cpu = 125
            elif "ryzen 7" in cpu_name or "i7" in cpu_name or "ultra 7" in cpu_name:
                est_cpu = 105

        if "gpu" in current_build:
            gpu_name = current_build["gpu"].get("name", "").lower()
            if any(k in gpu_name for k in ["9060 xt", "3060", "4060", "7600"]):
                est_gpu = 180
            elif any(k in gpu_name for k in ["5070", "5080", "5090", "9070", "4070", "4080"]):
                est_gpu = 280

        # Include 1.3x safety headroom multiplier
        return int((est_cpu + est_gpu + 50) * 1.3)
