$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Intraday environment is missing. Run .\setup_intraday.ps1 first."
}
& $Python -B -m compileall -q core scripts
if ($LASTEXITCODE -ne 0) { throw "Intraday compile check failed." }
Write-Host "INTRADAY STATIC VALIDATION: PASSED"
Write-Host "Run the daily workflow separately; it downloads data and writes local outputs."
