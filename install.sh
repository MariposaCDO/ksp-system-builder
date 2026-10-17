#!/usr/bin/env bash
# ==============================================================================
# ksp-system-builder Standalone Installer & Bootstrapper (POSIX)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================================"
echo " Starting setup for ksp-system-builder"
echo "========================================================================"

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed or not in PATH."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Found Python $PY_VERSION"

# 2. Check / Install uv
if ! command -v uv &>/dev/null; then
    echo "[INFO] 'uv' package manager not found. Installing uv..."
    if command -v curl &>/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    else
        echo "[INFO] Fallback: installing uv via pip..."
        python3 -m pip install --user uv
    fi
fi

if command -v uv &>/dev/null; then
    UV_CMD="uv"
else
    UV_CMD="python3 -m uv"
fi
echo "[OK] Package manager: $($UV_CMD --version)"

# 3. Virtual Environment Setup
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment (.venv)..."
    $UV_CMD venv .venv
fi

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 4. Install Dependencies
echo "[INFO] Installing locked & hashed dependencies..."
if [ -f "requirements.lock" ]; then
    $UV_CMD pip install --require-hashes -r requirements.lock
elif [ -f "requirements.txt" ]; then
    $UV_CMD pip install -r requirements.txt
else
    $UV_CMD pip install -e .
fi

# 5. Check Ollama
echo "[INFO] Checking Ollama service..."
if ! command -v ollama &>/dev/null; then
    echo "[WARNING] 'ollama' binary not found in PATH."
    echo "  -> If you plan to use local LLM natural-language extraction, install Ollama from https://ollama.com"
else
    echo "[OK] Ollama is installed."
fi

# 6. Run Self-Healer Preflight for Models & Catalogs
echo "[INFO] Running preflight & model dependency self-healer..."
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('backend').resolve()))
from ksp_pc_builder_agent_bundle import run_preflight_checks
from ollama.self_healer import OllamaSelfHealer

# Run catalog check
ok, _ = run_preflight_checks(stale_mode='ignore')
if not ok:
    print('[WARNING] Missing or corrupt catalogs. You can regenerate via download pipelines.')

# Run model self-heal
healer = OllamaSelfHealer()
if healer.is_service_online():
    ready, model_name = healer.heal_model_dependencies(auto_pull=True)
    if ready:
        print(f'[OK] Ollama self-healer verified model: {model_name}')
    else:
        print(f'[WARNING] Model self-healer: {model_name}')
else:
    print('[INFO] Ollama service is not currently running. Will fallback to rule-based parser when prompt is used.')
"

echo "========================================================================"
echo " Setup complete! To run the CLI:"
echo "   source .venv/bin/activate"
echo "   python frontend/cli/main.py --prompt \"Build a PC for Cyberpunk 2077 for 6000 ILS\""
echo "========================================================================"
