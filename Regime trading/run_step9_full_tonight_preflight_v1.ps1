param(
    [string]$NextSessionDate = "",
    [switch]$SkipFullSuite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if (-not $NextSessionDate) { $NextSessionDate = (Get-Date).AddDays(1).ToString("yyyy-MM-dd") }

function Invoke-PythonChecked {
    param([string[]]$Arguments, [string]$Label)
    Write-Host ""
    Write-Host "=== $Label ==="
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE." }
}

if (-not (Test-Path $Python -PathType Leaf)) { throw "Project virtual-environment Python is missing: $Python" }

$Required = @(
    "collect_step9i_v2_shadow_data.ps1",
    "run_step9i_v2_morning_shadow_router.ps1",
    "run_step9l_v3_morning_research_engine.ps1",
    "run_step9s_prospective_morning.ps1",
    "run_step9r_v1_prospective_shadow.ps1",
    "run_step9q_powerbi_snapshot.ps1",
    "run_step9tu_live_morning_v1.ps1",
    "tools\check_step9_full_morning_chain_v1.py",
    "tools\check_step9tu_morning_readiness_v1.py"
)
$Missing = @($Required | Where-Object { -not (Test-Path (Join-Path $Root $_) -PathType Leaf) })
if ($Missing.Count -gt 0) { throw "Required full-morning files are missing: $($Missing -join ', ')" }

$Offset = [TimeZoneInfo]::Local.GetUtcOffset((Get-Date))
if ($Offset.TotalHours -ne 2) { throw "Expected Stockholm summer-time offset +02:00; current offset is $Offset." }

$PendingReboot = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
if ($PendingReboot) { Write-Warning "Windows reports a pending reboot. Reboot tonight, never during the live morning." }

try {
    $Cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 CurrentClockSpeed, MaxClockSpeed
    Write-Host "CPU clock: $($Cpu.CurrentClockSpeed) / $($Cpu.MaxClockSpeed) MHz"
    if ([int]$Cpu.CurrentClockSpeed -lt 600) { Write-Warning "CPU appears severely throttled. Resolve the Dell charging slowdown tonight." }
} catch { Write-Warning "Could not read CPU clock: $($_.Exception.Message)" }

$Drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($Root).TrimEnd(':','\'))
Write-Host "Free disk: $([math]::Round($Drive.Free / 1GB, 2)) GB"
if ($Drive.Free -lt 1GB) { throw "Less than 1 GB free disk space remains." }

$Excel = @(Get-Process EXCEL -ErrorAction SilentlyContinue)
if ($Excel.Count -gt 0) { Write-Warning "Excel is open. Close the Step 9Q workbook before tomorrow morning." }

Invoke-PythonChecked -Label "FULL MORNING IMPORT SMOKE TEST" -Arguments @(
    "-c",
    "from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router, step9l_v3_selected_strategy_shadow_engine, step9s_prospective_contingency_shadow_v1, step9r_v1_candidate_ranking_research, step9q_powerbi_excel_feed, step9t_prospective_regime_transition_archetype_v1, step9u_prospective_contingency_selector_v1; print('FULL_MORNING_IMPORTS: PASSED')"
)

Invoke-PythonChecked -Label "FOCUSED FULL MORNING TESTS" -Arguments @(
    "-m", "pytest",
    "tests/test_step9i_v2_core5_plus_holdout18.py",
    "tests/test_step9l_v3_selected_strategy_shadow_engine.py",
    "tests/test_step9l_v3_compare_step9i_v2.py",
    "tests/test_step9s_prospective_contingency_shadow_v1.py",
    "tests/test_step9r_v1_candidate_ranking_research.py",
    "tests/test_step9q_powerbi_excel_feed.py",
    "tests/test_step9q_b_lite_live_trade_feed.py",
    "tests/test_step9t_prospective_regime_transition_archetype_v1.py",
    "tests/test_step9u_prospective_contingency_selector_v1.py",
    "tests/test_step9tu_morning_safety_v1.py",
    "tests/test_step9_full_morning_safety_v1.py",
    "-q"
)

Invoke-PythonChecked -Label "TEMPORARY STEP 9T -> STEP 9U LIFECYCLE VERIFIER" -Arguments @(
    "tools/verify_step9u_prospective_contingency_selector_v1.py"
)

if (-not $SkipFullSuite) {
    Invoke-PythonChecked -Label "FULL PROJECT COMPATIBILITY SUITE" -Arguments @("-m", "pytest", "-q")
}

$Marker = Join-Path $Logs ("step9_full_tonight_preflight_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$Payload = [ordered]@{
    status = "FULL_MORNING_PREFLIGHT_PASSED"
    created_at = (Get-Date).ToString("o")
    next_session_date = $NextSessionDate
    full_suite_run = (-not $SkipFullSuite.IsPresent)
    router_active = $false
    order_sent = $false
}
$Payload | ConvertTo-Json -Depth 4 | Set-Content -Path $Marker -Encoding utf8

Write-Host ""
Write-Host "STEP9_FULL_TONIGHT_PREFLIGHT_V1: PASSED"
Write-Host "NEXT SESSION DATE: $NextSessionDate"
Write-Host "Tomorrow run one command at 09:44:50: .\run_step9_full_live_morning_v1.ps1"
Write-Host "STEP 9S MANDATORY BENCHMARK CONTROL: TRUE"
Write-Host "STEP 9U MANDATORY CONTROL: FALSE"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
