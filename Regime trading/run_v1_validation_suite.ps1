param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Set-Location $ProjectRoot

function Invoke-ValidationModule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModuleName
    )

    & $Python -m $ModuleName
    if ($LASTEXITCODE -ne 0) {
        throw "Validation module failed: $ModuleName (exit code $LASTEXITCODE)"
    }
}

Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_portfolio"
Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_concentration"
Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_execution_stress"
Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_parameter_robustness"
Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_provider_quality"
Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_exposure_efficiency"
Invoke-ValidationModule "RegimeTrading.scripts.v1_validation_exposure_reconciliation"
