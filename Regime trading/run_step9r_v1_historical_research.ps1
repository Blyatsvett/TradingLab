param(
    [string]$StartDate = "2026-05-25",
    [string]$EndDate = "",
    [string]$SourceDb = "",
    [string]$V3Ledger = "",
    [string]$TaxonomyLedger = "",
    [string]$OutputDb = "",
    [switch]$SkipAuthoritativeCheck,
    [switch]$NoRebuildMissingTaxonomy
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Local virtual environment not found. Run .\setup_regime_trading.ps1 first."
}

$HistoricalArguments = @(
    "-m",
    "RegimeTrading.scripts.step9r_v1_candidate_ranking_research",
    "historical",
    "--start-date",
    $StartDate
)

if ($EndDate) {
    $HistoricalArguments += @("--end-date", $EndDate)
}
if ($SourceDb) {
    $HistoricalArguments += @("--source-db", $SourceDb)
}
if ($V3Ledger) {
    $HistoricalArguments += @("--v3-ledger", $V3Ledger)
}
if ($TaxonomyLedger) {
    $HistoricalArguments += @("--taxonomy-ledger", $TaxonomyLedger)
}
if ($OutputDb) {
    $HistoricalArguments += @("--output-db", $OutputDb)
}
if ($SkipAuthoritativeCheck) {
    $HistoricalArguments += "--skip-authoritative-check"
}
if ($NoRebuildMissingTaxonomy) {
    $HistoricalArguments += "--no-rebuild-missing-taxonomy"
}

Write-Host "`n=== STEP 9R V1: EXACT HISTORICAL CANDIDATE REPLAY ==="
& $Python @HistoricalArguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9R V1 historical replay failed with exit code $LASTEXITCODE."
}

$ResearchDbForModels = if ($OutputDb) { $OutputDb } else { "data\ledgers\research\step9r_candidate_ranking_research_v1.db" }
$ModelArguments = @(
    "-m",
    "RegimeTrading.scripts.step9r_v1_candidate_ranking_research",
    "models",
    "--research-db",
    $ResearchDbForModels
)

# Model fitting intentionally runs in a fresh Python process after the exact
# replay. This isolates the research models from legacy replay monkey-patches
# and numerical-library state.
Write-Host "`n=== STEP 9R V1: WALK-FORWARD SELECTOR CHALLENGERS ==="
& $Python @ModelArguments
if ($LASTEXITCODE -ne 0) {
    throw "Step 9R V1 selector-model comparison failed with exit code $LASTEXITCODE."
}

Write-Host "`n=== STEP 9R V1 HISTORICAL RESEARCH COMPLETE ==="
Write-Host "V3 was not changed. No order was sent."
