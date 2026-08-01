$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found: $python. Run setup_regime_trading.ps1 first."
}

& $python -m RegimeTrading.scripts.step9f_sector_ticker_strategy_experiments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9F sector/ticker strategy experiments failed with exit code $LASTEXITCODE"
}
