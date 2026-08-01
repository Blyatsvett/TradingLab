param(
    [string]$FrozenLedger = "",
    [string]$ResearchLedger = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }
$Arguments = @("-m", "RegimeTrading.scripts.step9l_v3_compare_step9i_v2")
if ($FrozenLedger) { $Arguments += @("--frozen-ledger", $FrozenLedger) }
if ($ResearchLedger) { $Arguments += @("--research-ledger", $ResearchLedger) }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Step 9I V2 versus Step 9L V3 comparison failed with exit code $LASTEXITCODE." }
