param(
    [string]$Date = ""
)

$ErrorActionPreference = "Stop"

$arguments = @(
    "-m",
    "RegimeTrading.scripts.step9s_prospective_contingency_shadow_v1",
    "eod"
)

if ($Date) {
    $arguments += @("--date", $Date)
}

python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9S prospective EOD evaluation failed. Do not rerun an already sealed morning engine."
}
