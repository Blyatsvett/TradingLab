$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Swing environment is missing. Run .\setup_swing.ps1 first."
}
& $Python -B -m compileall -q core tests
if ($LASTEXITCODE -ne 0) { throw "Swing compile check failed." }
& $Python -B -m py_compile scripts\run_canonical_backtest.py
if ($LASTEXITCODE -ne 0) { throw "Swing canonical runner compile check failed." }
& $Python -B -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Swing tests failed with exit code $LASTEXITCODE." }
Write-Host "SWING VALIDATION: PASSED"
