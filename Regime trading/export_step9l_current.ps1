$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& ".\export_step9l_v3_research_ledgers.ps1"
if ($LASTEXITCODE -ne 0) { throw "Current Step 9L export failed with exit code $LASTEXITCODE." }
