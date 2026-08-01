param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

& ".\.venv\Scripts\python.exe" -m RegimeTrading.scripts.v1_validation_execution_stress
