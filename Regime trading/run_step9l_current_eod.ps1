param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowEarlyEvaluation
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& ".\run_step9l_v3_eod_research_engine.ps1" @PSBoundParameters
if ($LASTEXITCODE -ne 0) { throw "Current Step 9L EOD engine failed with exit code $LASTEXITCODE." }
