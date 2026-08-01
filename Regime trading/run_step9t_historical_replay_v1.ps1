param(
    [string]$StartDate = "",
    [string]$EndDate = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Arguments = @(
    "-m",
    "RegimeTrading.scripts.step9t_regime_transition_archetype_research_v1"
)

if ($StartDate) {
    $Arguments += @("--start-date", $StartDate)
}

if ($EndDate) {
    $Arguments += @("--end-date", $EndDate)
}

& python @Arguments
exit $LASTEXITCODE
