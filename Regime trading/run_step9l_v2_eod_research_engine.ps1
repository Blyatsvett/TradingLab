param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowEarlyEvaluation
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }
$Arguments = @("-m", "RegimeTrading.scripts.step9l_v2_selected_strategy_shadow_engine", "eod")
if ($Date) { $Arguments += @("--date", $Date) }
if ($AsOf) { $Arguments += @("--as-of", $AsOf) }
if ($AllowEarlyEvaluation) { $Arguments += "--allow-early-evaluation" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Step 9L V2 EOD research engine failed with exit code $LASTEXITCODE." }
