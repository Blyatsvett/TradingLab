$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Pattern Trading environment is missing. Run .\setup_pattern_trading.ps1 first."
}

& $Python -B -m compileall -q `
    black_friday_event_study\src `
    labor_day_event_study\src `
    labor_day_event_study\tests
if ($LASTEXITCODE -ne 0) { throw "Pattern Trading compile check failed." }
& $Python -B -m py_compile `
    black_friday_event_study\run_pipeline.py `
    labor_day_event_study\audit_prices.py `
    labor_day_event_study\universe.py
if ($LASTEXITCODE -ne 0) { throw "Pattern Trading entry-point compile check failed." }

Push-Location (Join-Path $PSScriptRoot "labor_day_event_study")
try {
    & $Python -B -m pytest -q -p no:cacheprovider tests
    if ($LASTEXITCODE -ne 0) { throw "Labor Day event-study tests failed." }
}
finally {
    Pop-Location
}
Write-Host "PATTERN TRADING VALIDATION: PASSED"
