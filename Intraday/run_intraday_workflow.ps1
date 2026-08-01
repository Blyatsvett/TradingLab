$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Intraday environment is missing. Run .\setup_intraday.ps1 first."
}
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$OldPythonPath = $env:PYTHONPATH
if ($OldPythonPath) {
    $env:PYTHONPATH = "$RepositoryRoot;$OldPythonPath"
}
else {
    $env:PYTHONPATH = $RepositoryRoot
}
$WorkflowExitCode = 0
try {
    & $Python -B -m Intraday.scripts.run_daily_orb_workflow
    $WorkflowExitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $OldPythonPath
}
if ($WorkflowExitCode -ne 0) { throw "Intraday workflow failed with exit code $WorkflowExitCode." }
