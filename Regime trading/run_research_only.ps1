$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first."
}

& $Python -m RegimeTrading.scripts.sync_intraday_database
& $Python -m RegimeTrading.scripts.research_regime_aware_gap_recovery
