param(
    [switch]$Headless,
    [switch]$SkipDownload,
    [int]$MaxFiles = 2000,
    [int]$LookbackHours = 48
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Set-Location $Root

$CollectorArgs = @(
    "-m",
    "RegimeTrading.scripts.collect_nasdaq_posttrade",
    "--max-files", "$MaxFiles",
    "--lookback-hours", "$LookbackHours"
)

if ($Headless) {
    $CollectorArgs += "--headless"
}

if ($SkipDownload) {
    $CollectorArgs += "--skip-download"
}

Write-Host ""
Write-Host "RUNNING NASDAQ FORWARD DATA COLLECTION"
Write-Host "Project root : $Root"
Write-Host "Max files    : $MaxFiles"
Write-Host "Lookback     : $LookbackHours hours"
Write-Host ""

& $Python @CollectorArgs
if ($LASTEXITCODE -ne 0) {
    throw "Nasdaq collection failed with exit code $LASTEXITCODE"
}

& $Python -m RegimeTrading.scripts.compare_nasdaq_yahoo
if ($LASTEXITCODE -ne 0) {
    throw "Nasdaq/Yahoo comparison failed with exit code $LASTEXITCODE"
}

& $Python -m RegimeTrading.scripts.compare_gap_recovery_decisions
if ($LASTEXITCODE -ne 0) {
    throw "Strategy-decision comparison failed with exit code $LASTEXITCODE"
}

& $Python -m RegimeTrading.scripts.v1_validation_provider_quality
if ($LASTEXITCODE -ne 0) {
    throw "Provider-quality validation failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "NASDAQ FORWARD DATA COLLECTION COMPLETE"
