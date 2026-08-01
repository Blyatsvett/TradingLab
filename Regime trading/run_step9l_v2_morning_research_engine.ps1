param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowLateReconstruction
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }
$Arguments = @("-m", "RegimeTrading.scripts.step9l_v2_selected_strategy_shadow_engine", "morning")
if ($Date) { $Arguments += @("--date", $Date) }
if ($AsOf) { $Arguments += @("--as-of", $AsOf) }
if ($AllowLateReconstruction) { $Arguments += "--allow-late-reconstruction" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Step 9L V2 morning research engine failed with exit code $LASTEXITCODE." }
