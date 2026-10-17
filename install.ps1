<#
.SYNOPSIS
    ksp-system-builder Standalone Installer & Bootstrapper (Windows PowerShell)
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " Starting setup for ksp-system-builder (Windows)" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

# 1. Check Python
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Error "[ERROR] Python 3 is not installed or not found in PATH."
    exit 1
}

$PyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[OK] Found Python $PyVersion" -ForegroundColor Green

# 2. Check / Install uv
$UvCmd = Get-Command uv -ErrorAction SilentlyContinue
$UvExec = "uv"

if (-not $UvCmd) {
    # Check if python -m uv works
    $UvPyModule = & python -m uv --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        $UvExec = "python -m uv"
    } else {
        Write-Host "[INFO] 'uv' package manager not found. Installing uv via pip..." -ForegroundColor Yellow
        & python -m pip install --user uv
        $UvExec = "python -m uv"
    }
}

Write-Host "[OK] Package manager is ready." -ForegroundColor Green

# 3. Virtual Environment Setup
if (-not (Test-Path ".venv")) {
    Write-Host "[INFO] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    Invoke-Expression "$UvExec venv .venv"
}

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = "python"
}

# 4. Install Dependencies
Write-Host "[INFO] Installing dependencies..." -ForegroundColor Yellow
if (Test-Path "requirements.lock") {
    Invoke-Expression "$UvExec pip install --require-hashes -r requirements.lock"
} elseif (Test-Path "requirements.txt") {
    Invoke-Expression "$UvExec pip install -r requirements.txt"
} else {
    Invoke-Expression "$UvExec pip install -e ."
}

# 5. Check Ollama
$OllamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $OllamaCmd) {
    Write-Host "[WARNING] 'ollama' CLI not found in PATH." -ForegroundColor Yellow
    Write-Host "  -> If you plan to use local LLM natural-language extraction, install Ollama from https://ollama.com" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Ollama binary detected." -ForegroundColor Green
}

# 6. Run Self-Healer Preflight for Models & Catalogs
Write-Host "[INFO] Running preflight & model dependency self-healer..." -ForegroundColor Yellow
& $VenvPython -c @"
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
"@

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " Setup complete! To run the CLI:" -ForegroundColor Cyan
Write-Host "   .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "   python frontend/cli/main.py --prompt ""Build a PC for Cyberpunk 2077 for 6000 ILS""" -ForegroundColor White
Write-Host "========================================================================" -ForegroundColor Cyan
