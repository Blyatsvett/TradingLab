param(
    [string]$Date = ""
)

$ErrorActionPreference = "Stop"

$arguments = @(
    "-m",
    "RegimeTrading.scripts.step9s_prospective_contingency_shadow_v1",
    "morning"
)

if ($Date) {
    $arguments += @("--date", $Date)
}

python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9S prospective morning assignment failed. Do not rerun Step 9I or Step 9L."
}
