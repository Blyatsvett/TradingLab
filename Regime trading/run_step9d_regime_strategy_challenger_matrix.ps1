$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

& $Python -m RegimeTrading.scripts.step9d_regime_strategy_challenger_matrix
if ($LASTEXITCODE -ne 0) {
    throw "Step 9D challenger matrix failed with exit code $LASTEXITCODE"
}
