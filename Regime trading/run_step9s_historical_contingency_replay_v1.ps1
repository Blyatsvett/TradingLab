$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
.\.venv\Scripts\Activate.ps1
python -m RegimeTrading.scripts.step9s_historical_contingency_replay_v1
if ($LASTEXITCODE -ne 0) { throw "Step 9S historical contingency replay failed." }
