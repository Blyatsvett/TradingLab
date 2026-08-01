param(
    [string]$StartDate = "2026-05-25",
    [string]$EndDate = "2026-07-24",
    [switch]$ResetReplay
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found at $Python. Run .\setup_regime_trading.ps1 first."
}

$argsList = @(
    "-m", "RegimeTrading.scripts.step9ir_historical_walk_forward_replay",
    "--start-date", $StartDate,
    "--end-date", $EndDate
)
if ($ResetReplay) {
    $argsList += "--reset-replay"
}

& $Python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Step 9I-R historical replay failed with exit code $LASTEXITCODE."
}
