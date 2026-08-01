$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Set-Location $Root

Write-Host ""
Write-Host "RUNNING GAP RECOVERY STRATEGY-DECISION COMPARISON"
Write-Host "Project root: $Root"
Write-Host ""

& $Python -m RegimeTrading.scripts.compare_gap_recovery_decisions
if ($LASTEXITCODE -ne 0) {
    throw "Strategy-decision comparison failed with exit code $LASTEXITCODE"
}

& $Python -m RegimeTrading.scripts.v1_validation_provider_quality
if ($LASTEXITCODE -ne 0) {
    throw "Provider-quality validation failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "STRATEGY-DECISION COMPARISON COMPLETE"
