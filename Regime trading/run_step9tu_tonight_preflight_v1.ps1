param(
    [string]$NextSessionDate = "",
    [switch]$SkipFocusedTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

if (-not $NextSessionDate) {
    $NextSessionDate = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
}

function Invoke-PythonChecked {
    param([string[]]$Arguments, [string]$Label)
    Write-Host ""
    Write-Host "=== $Label ==="
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Project virtual-environment Python is missing: $Python"
}

$Required = @(
    "run_step9t_prospective_snapshot_v1.ps1",
    "run_step9u_prospective_selection_v1.ps1",
    "RegimeTrading\scripts\step9t_prospective_regime_transition_archetype_v1.py",
    "RegimeTrading\scripts\step9u_prospective_contingency_selector_v1.py",
    "tools\verify_step9u_prospective_contingency_selector_v1.py",
    "tools\check_step9tu_morning_readiness_v1.py",
    "data\archives\freezes\step9t_regime_transition_archetype_research_v1\freeze_92b274cb24cad391\STEP9T_HISTORICAL_REPLAY_V1_FREEZE_MANIFEST.json",
    "data\archives\freezes\step9u_historical_contingency_selector_v1\freeze_8042ad803be28ccf\STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1_FREEZE_MANIFEST.json"
)
$Missing = @($Required | Where-Object { -not (Test-Path (Join-Path $Root $_) -PathType Leaf) })
if ($Missing.Count -gt 0) {
    throw "Required morning files are missing: $($Missing -join ', ')"
}

$TimeZone = Get-TimeZone
$Offset = [TimeZoneInfo]::Local.GetUtcOffset((Get-Date))
Write-Host "Local time zone : $($TimeZone.Id)"
Write-Host "Current offset  : $Offset"
if ($Offset.TotalHours -ne 2) {
    throw "Expected Stockholm summer-time offset +02:00; current local offset is $Offset."
}

$PendingReboot = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
if ($PendingReboot) {
    Write-Warning "Windows reports a pending reboot. Reboot tonight, not during tomorrow's trading window."
}

try {
    $Processor = Get-CimInstance Win32_Processor | Select-Object -First 1 CurrentClockSpeed, MaxClockSpeed
    Write-Host "CPU clock       : $($Processor.CurrentClockSpeed) / $($Processor.MaxClockSpeed) MHz"
    if ([int]$Processor.CurrentClockSpeed -lt 600) {
        Write-Warning "CPU appears severely throttled. Resolve the Dell charging slowdown before the morning window."
    }
} catch {
    Write-Warning "Could not read CPU clock: $($_.Exception.Message)"
}

Invoke-PythonChecked -Label "PYTHON IMPORT AND FREEZE SMOKE TEST" -Arguments @(
    "-c",
    "from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as t; from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as u; assert t._historical_freeze_provenance()['freeze_id']=='92b274cb24cad391'; assert u._historical_freeze_provenance()['freeze_id']=='8042ad803be28ccf'; print('FREEZES_AND_IMPORTS: PASSED')"
)

if (-not $SkipFocusedTests) {
    Invoke-PythonChecked -Label "FOCUSED STEP 9T / STEP 9U / MORNING-SAFETY TESTS" -Arguments @(
        "-m", "pytest",
        "tests/test_step9t_prospective_regime_transition_archetype_v1.py",
        "tests/test_step9u_prospective_contingency_selector_v1.py",
        "tests/test_step9tu_morning_safety_v1.py",
        "-q"
    )
}

Invoke-PythonChecked -Label "TEMPORARY END-TO-END STEP 9T -> STEP 9U VERIFIER" -Arguments @(
    "tools/verify_step9u_prospective_contingency_selector_v1.py"
)

$Marker = Join-Path $Logs ("step9tu_tonight_preflight_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$Payload = [ordered]@{
    status = "TONIGHT_PREFLIGHT_PASSED"
    created_at = (Get-Date).ToString("o")
    next_session_date = $NextSessionDate
    timezone = $TimeZone.Id
    utc_offset_hours = $Offset.TotalHours
    focused_tests_run = (-not $SkipFocusedTests.IsPresent)
    real_step9u_prospective_ledger_created = (Test-Path (Join-Path $Root "data\step9u_contingency_selector_prospective_shadow_v1.db"))
    router_active = $false
    order_sent = $false
}
$Payload | ConvertTo-Json -Depth 5 | Set-Content -Path $Marker -Encoding utf8

Write-Host ""
Write-Host "STEP9TU_TONIGHT_PREFLIGHT_V1: PASSED"
Write-Host "NEXT SESSION DATE: $NextSessionDate"
Write-Host "Marker: $Marker"
Write-Host "Run .\run_step9tu_morning_readiness_v1.ps1 around 09:46 tomorrow."
Write-Host "Run .\run_step9tu_live_morning_v1.ps1 at 09:47:45 tomorrow."
Write-Host "MANDATORY CONTROL ACTIVE: FALSE"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
