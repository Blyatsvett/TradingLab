$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m RegimeTrading.scripts.step9u_historical_contingency_selector_v1 @args
if ($LASTEXITCODE -ne 0) {
    throw "Step 9U historical contingency selector replay failed."
}
