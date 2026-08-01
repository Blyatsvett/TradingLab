param(
    [string]$StartDate = "2026-05-25",
    [string]$EndDate = "2026-07-24",
    [string]$SourceDb = ""
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found at $Python. Run .\setup_regime_trading.ps1 first."
}
$Arguments = @(
    "-m", "RegimeTrading.scripts.step9k_high_dispersion_strategy_research",
    "--start-date", $StartDate,
    "--end-date", $EndDate
)
if ($SourceDb) { $Arguments += @("--source-db", $SourceDb) }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9K HIGH_DISPERSION research failed with exit code $LASTEXITCODE."
}
