param(
    [int]$Days = 5,
    [string]$Interval = "5m",
    [switch]$SkipBootstrap
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }
# The existing 29-ticker Step 9I market-data database already contains all 11 regime-source tickers,
# including the Core 5, plus the 18 holdout tickers. V2 intentionally reuses that market-data store.
$Arguments = @("-m", "RegimeTrading.scripts.collect_step9i_shadow_data", "--days", "$Days", "--interval", $Interval)
if ($SkipBootstrap) { $Arguments += "--skip-bootstrap" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Step 9I V2 data collection failed with exit code $LASTEXITCODE." }
