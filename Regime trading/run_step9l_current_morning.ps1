param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowLateReconstruction
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& ".\run_step9l_v3_morning_research_engine.ps1" @PSBoundParameters
if ($LASTEXITCODE -ne 0) { throw "Current Step 9L morning engine failed with exit code $LASTEXITCODE." }
