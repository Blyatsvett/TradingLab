param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Set-Location $ProjectRoot

& $Python -m RegimeTrading.scripts.step7_regime_feature_foundation
if ($LASTEXITCODE -ne 0) {
    throw "Step 7 regime feature foundation failed (exit code $LASTEXITCODE)"
}
