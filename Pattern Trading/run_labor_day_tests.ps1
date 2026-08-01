$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Pattern Trading environment is missing. Run .\setup_pattern_trading.ps1 first."
}
Set-Location -LiteralPath (Join-Path $ProjectRoot "labor_day_event_study")
& $Python -B -m pytest -q -p no:cacheprovider tests
if ($LASTEXITCODE -ne 0) { throw "Labor Day event-study tests failed with exit code $LASTEXITCODE." }
