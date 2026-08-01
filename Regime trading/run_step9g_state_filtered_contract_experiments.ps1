$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found: $python"
}

& $python -m RegimeTrading.scripts.step9g_state_filtered_contract_experiments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9G state-filtered contract experiment failed with exit code $LASTEXITCODE"
}
