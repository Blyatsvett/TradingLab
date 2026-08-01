param(
    [string]$StartDate = "2026-05-25",
    [string]$EndDate = "2026-07-24",
    [string]$SourceDb = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Virtual environment Python not found at $Python" }
$Arguments = @(
    "-m", "RegimeTrading.scripts.step9j_v2_combined23_challenger_redesign",
    "--start-date", $StartDate,
    "--end-date", $EndDate
)
if ($SourceDb) { $Arguments += @("--source-db", $SourceDb) }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Step 9J V2 exited with code $LASTEXITCODE" }
