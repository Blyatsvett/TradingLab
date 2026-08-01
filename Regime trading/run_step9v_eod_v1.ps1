Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) { throw "Python environment not found: $Python" }
Set-Location $ProjectRoot
function Invoke-NativeSafe([string[]]$Arguments) {
    $OldPreference = $ErrorActionPreference
    try { $ErrorActionPreference = "Continue"; & $Python @Arguments; $ExitCode = $LASTEXITCODE }
    finally { $ErrorActionPreference = $OldPreference }
    if ($ExitCode -ne 0) { throw "Python command failed with exit code ${ExitCode}: $($Arguments -join ' ')" }
}
Write-Host "Refreshing final raw prices only before Step 9V EOD..."
Invoke-NativeSafe @("-m","RegimeTrading.scripts.collect_step9i_shadow_data","--days","2","--interval","5m","--skip-bootstrap")
Invoke-NativeSafe @("-m","RegimeTrading.scripts.step9v_intraday_regime_transition_observer_v1","eod")
Invoke-NativeSafe @("-m","RegimeTrading.scripts.step9v_intraday_regime_transition_observer_v1","audit")
