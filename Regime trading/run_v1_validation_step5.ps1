param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Set-Location $ProjectRoot
Write-Host ""
Write-Host "RUNNING V1 VALIDATION SUITE STEP 5"
Write-Host "Provider quality and session completeness gates"
Write-Host ""

& $Python -m RegimeTrading.scripts.v1_validation_provider_quality
if ($LASTEXITCODE -ne 0) {
    throw "Step 5 validation failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "V1 VALIDATION SUITE STEP 5 COMPLETE"
