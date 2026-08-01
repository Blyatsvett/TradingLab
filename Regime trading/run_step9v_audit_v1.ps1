Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Set-Location $ProjectRoot
$OldPreference = $ErrorActionPreference
try { $ErrorActionPreference = "Continue"; & $Python -m RegimeTrading.scripts.step9v_intraday_regime_transition_observer_v1 audit; $ExitCode = $LASTEXITCODE }
finally { $ErrorActionPreference = $OldPreference }
if ($ExitCode -ne 0) { throw "Step 9V audit failed with exit code $ExitCode" }
