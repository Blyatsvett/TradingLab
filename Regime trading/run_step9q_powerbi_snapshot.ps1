param(
    [string]$Date = "",
    [string]$Output = "",
    [switch]$RequireBothEngines
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first."
}

$Arguments = @(
    "-m",
    "RegimeTrading.scripts.step9q_powerbi_excel_feed"
)

if ($Date) {
    $Arguments += @("--date", $Date)
}
if ($Output) {
    $Arguments += @("--output", $Output)
}
if ($RequireBothEngines) {
    $Arguments += "--require-both-engines"
}

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9Q-B Lite Power BI Excel snapshot failed with exit code $LASTEXITCODE."
}
