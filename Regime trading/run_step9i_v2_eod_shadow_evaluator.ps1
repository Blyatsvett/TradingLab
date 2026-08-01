param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowEarlyEvaluation
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }
$Arguments = @("-m", "RegimeTrading.scripts.step9i_v2_core5_plus_holdout18_shadow_router", "eod")
if ($Date) { $Arguments += @("--date", $Date) }
if ($AsOf) { $Arguments += @("--as-of", $AsOf) }
if ($AllowEarlyEvaluation) { $Arguments += "--allow-early-evaluation" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Step 9I V2 EOD evaluator failed with exit code $LASTEXITCODE." }
