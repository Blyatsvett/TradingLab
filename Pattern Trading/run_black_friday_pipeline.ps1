$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Pattern Trading environment is missing. Run .\setup_pattern_trading.ps1 first."
}
Set-Location -LiteralPath (Join-Path $ProjectRoot "black_friday_event_study")
& $Python -B run_pipeline.py
if ($LASTEXITCODE -ne 0) { throw "Black Friday event-study pipeline failed with exit code $LASTEXITCODE." }
