$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Swing environment is missing. Run .\setup_swing.ps1 first."
}
& $Python -B -m scripts.run_canonical_backtest
if ($LASTEXITCODE -ne 0) { throw "Swing canonical backtest failed with exit code $LASTEXITCODE." }
