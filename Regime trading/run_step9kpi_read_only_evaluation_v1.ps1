[CmdletBinding()]
param(
    [string[]]$Date,
    [string]$ProjectRoot = $PSScriptRoot,
    [string]$OutputDirectory,
    [string]$Workbook,
    [string]$July29MockProjectRoot,
    [switch]$SkipJuly29Mock
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Config = Join-Path $ProjectRoot "config\step9kpi_read_only_evaluation_v1.json"
$Schema = Join-Path $ProjectRoot "config\step9kpi_output_schema_v1.json"
$PathConfig = Get-Content -LiteralPath (Join-Path $ProjectRoot "config\paths.json") -Raw | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot ([string]$PathConfig.kpi_output_dir)
}
if ([string]::IsNullOrWhiteSpace($Workbook)) {
    $Workbook = Join-Path $OutputDirectory "powerbi_step9_kpi_monitor.xlsx"
}

foreach ($RequiredPath in @($Python, $Config, $Schema)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required Step 9 KPI file not found: $RequiredPath"
    }
}

$RequestedDates = [System.Collections.Generic.List[string]]::new()
foreach ($SessionDate in $Date) {
    if (-not [string]::IsNullOrWhiteSpace($SessionDate)) {
        [void]$RequestedDates.Add($SessionDate)
    }
}

$Arguments = @(
    "-m",
    "RegimeTrading.scripts.step9kpi_read_only_evaluation_v1",
    "build",
    "--project-root", $ProjectRoot,
    "--config", $Config,
    "--schema", $Schema,
    "--output-dir", $OutputDirectory,
    "--workbook", $Workbook
)

foreach ($SessionDate in $RequestedDates) {
    $Arguments += @("--date", $SessionDate)
}

$IncludeJuly29Mock = -not $SkipJuly29Mock
if ($RequestedDates.Count -gt 0 -and -not $RequestedDates.Contains("2026-07-29")) {
    $IncludeJuly29Mock = $false
}

if ($IncludeJuly29Mock) {
    if ([string]::IsNullOrWhiteSpace($July29MockProjectRoot)) {
        $TradingLabRoot = Split-Path -Parent $ProjectRoot
        $MockParent = Join-Path $TradingLabRoot "Regime trading mock sessions"
        if (Test-Path -LiteralPath $MockParent -PathType Container) {
            $MockMatches = @(
                Get-ChildItem `
                    -LiteralPath $MockParent `
                    -Directory `
                    -Filter "MOCK_20260729_FULL_CHAIN_REHEARSAL_*" |
                Sort-Object LastWriteTime -Descending
            )
            if ($MockMatches.Length -gt 0) {
                $July29MockProjectRoot = $MockMatches[0].FullName
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($July29MockProjectRoot)) {
        $July29MockProjectRoot = [System.IO.Path]::GetFullPath($July29MockProjectRoot)
        $RequiredMockPaths = @(
            (Join-Path $July29MockProjectRoot "data\step9i_shadow_intraday_prices.db"),
            (Join-Path $July29MockProjectRoot "data\step9l_v3_selected_strategy_shadow_ledger.db"),
            (Join-Path $July29MockProjectRoot "data\step9u_contingency_selector_prospective_shadow_v1.db")
        )
        foreach ($MockPath in $RequiredMockPaths) {
            if (-not (Test-Path -LiteralPath $MockPath -PathType Leaf)) {
                throw "July 29 mock source is incomplete; missing: $MockPath"
            }
        }
        $Arguments += @(
            "--supplemental-project-root", $July29MockProjectRoot,
            "--supplemental-date", "2026-07-29"
        )
    }
    else {
        Write-Warning "July 29 mock project was not found. The workbook will contain real-project sessions only."
    }
}

Set-Location -LiteralPath $ProjectRoot

Write-Host "=== STEP 9 KPI READ-ONLY EVALUATION V1.1 ==="
Write-Host "Project root : $ProjectRoot"
Write-Host "Output folder: $OutputDirectory"
Write-Host "Workbook     : $Workbook"
if ($RequestedDates.Count -gt 0) {
    Write-Host "Session dates: $($RequestedDates -join ', ')"
}
else {
    Write-Host "Session dates: all sealed real sessions"
}
if (-not [string]::IsNullOrWhiteSpace($July29MockProjectRoot) -and $IncludeJuly29Mock) {
    Write-Host "Mock source  : $July29MockProjectRoot"
    Write-Host "Mock session : 2026-07-29 / MOCK_REHEARSAL"
}
else {
    Write-Host "Mock session : not included"
}

$PreviousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $Output = @(& $Python @Arguments 2>&1)
    $ExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousPreference
}

$Output | ForEach-Object { Write-Host ([string]$_) }

if ($ExitCode -ne 0) {
    throw "Step 9 KPI build failed with exit code ${ExitCode}: $($Arguments -join ' ')"
}

if (-not (Test-Path -LiteralPath $Workbook -PathType Leaf)) {
    throw "Step 9 KPI build returned success but workbook is missing: $Workbook"
}

Write-Host ""
Write-Host "STEP9KPI_READ_ONLY_EVALUATION_V1.1: REFRESHED"
Write-Host "POWER BI WORKBOOK: $Workbook"
Write-Host "JULY 29 MOCK INCLUDED: $IncludeJuly29Mock"
Write-Host "SOURCE ACCESS: READ_ONLY"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
