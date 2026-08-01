param(
    [string]$FrozenLedger = "",
    [string]$ResearchLedger = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& ".\compare_step9i_v2_vs_step9l_v3.ps1" @PSBoundParameters
if ($LASTEXITCODE -ne 0) { throw "Step 9I V2 versus current Step 9L comparison failed with exit code $LASTEXITCODE." }
