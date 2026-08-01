param(
    [int]$Days = 5,
    [string]$Interval = "5m",
    [switch]$SkipBootstrap
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first." }

$Arguments = @("-m", "RegimeTrading.scripts.collect_step9i_shadow_data", "--days", "$Days", "--interval", $Interval)
if ($SkipBootstrap) { $Arguments += "--skip-bootstrap" }
& $Python @Arguments
