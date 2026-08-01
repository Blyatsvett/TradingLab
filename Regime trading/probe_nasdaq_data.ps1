$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

& $Python -m RegimeTrading.scripts.probe_nasdaq_posttrade
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
