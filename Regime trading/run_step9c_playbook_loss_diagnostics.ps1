$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run .\setup_regime_trading.ps1 first."
}

& ".\.venv\Scripts\python.exe" -m RegimeTrading.scripts.step9c_playbook_loss_diagnostics
if ($LASTEXITCODE -ne 0) {
    throw "Step 9C playbook loss-driver diagnostics failed with exit code $LASTEXITCODE."
}
