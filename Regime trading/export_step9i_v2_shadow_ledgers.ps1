$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }
& $Python -m RegimeTrading.scripts.step9i_v2_core5_plus_holdout18_shadow_router export
if ($LASTEXITCODE -ne 0) { throw "Step 9I V2 export failed with exit code $LASTEXITCODE." }
