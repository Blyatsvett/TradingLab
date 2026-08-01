$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -m venv .venv
    }
    else {
        python -m venv .venv
    }
}

& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".venv\Scripts\python.exe" tools\check_dependencies.py
if ($LASTEXITCODE -ne 0) {
    throw "Regime Trading dependency verification failed. SciPy is required by Step 9R and by the repaired yfinance collectors."
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run the project with:"
Write-Host '.\run_regime_research.ps1'
Write-Host 'Validate the project with:'
Write-Host '.\tools\run_project_validation.ps1'
