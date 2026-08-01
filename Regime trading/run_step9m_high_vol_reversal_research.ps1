param(
    [string]$StartDate = "2026-05-25",
    [string]$EndDate = "2026-07-24",
    [string]$SourceDb = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python"
}

$Arguments = @(
    "-m", "RegimeTrading.scripts.step9m_high_vol_reversal_strategy_research",
    "--start-date", $StartDate,
    "--end-date", $EndDate
)
if ($SourceDb) {
    $Arguments += @("--source-db", $SourceDb)
}

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9M failed with exit code $LASTEXITCODE"
}
