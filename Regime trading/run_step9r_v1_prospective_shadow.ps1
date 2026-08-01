param(
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [string]$SourceDb = "",
    [string]$V3Ledger = "",
    [string]$ResearchDb = "",
    [string]$ProspectiveDb = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first."
}

$Arguments = @(
    "-m",
    "RegimeTrading.scripts.step9r_v1_candidate_ranking_research",
    "morning",
    "--date",
    $Date
)

if ($SourceDb) { $Arguments += @("--source-db", $SourceDb) }
if ($V3Ledger) { $Arguments += @("--v3-ledger", $V3Ledger) }
if ($ResearchDb) { $Arguments += @("--research-db", $ResearchDb) }
if ($ProspectiveDb) { $Arguments += @("--prospective-db", $ProspectiveDb) }

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9R V1 prospective shadow selector failed with exit code $LASTEXITCODE."
}
