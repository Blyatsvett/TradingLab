param(
    [string]$Date = "",
    [int]$CollectorDays = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if (-not $Date) { $Date = (Get-Date).ToString("yyyy-MM-dd") }

if (-not (Test-Path $Python -PathType Leaf)) { throw "Project virtual-environment Python is missing: $Python" }
if ((Get-Date).ToString("yyyy-MM-dd") -ne $Date) { throw "Full live morning may only run for today's date." }

$Now = Get-Date
$LaunchEarliest = Get-Date -Hour 9 -Minute 44 -Second 40
$LaunchLatest = Get-Date -Hour 9 -Minute 45 -Second 35
$CollectorStart = Get-Date -Hour 9 -Minute 45 -Second 2
$Step9TULaunchEarliest = Get-Date -Hour 9 -Minute 47 -Second 35
$Step9TUDeadline = Get-Date -Hour 9 -Minute 48 -Second 45
if ($Now -lt $LaunchEarliest) { throw "Launch no earlier than 09:44:40. Current: $($Now.ToString('HH:mm:ss'))." }
if ($Now -gt $LaunchLatest) { throw "Full-chain launch deadline 09:45:35 passed. Current: $($Now.ToString('HH:mm:ss'))." }

$Offset = [TimeZoneInfo]::Local.GetUtcOffset($Now)
if ($Offset.TotalHours -ne 2) { throw "Expected Stockholm summer-time offset +02:00; current offset is $Offset." }

$MutexName = "STEP9_FULL_MORNING_$($Date.Replace('-', ''))"
$Mutex = [System.Threading.Mutex]::new($false, $MutexName)
if (-not $Mutex.WaitOne(0)) { $Mutex.Dispose(); throw "Another full morning wrapper is already running. Do not double-click." }

try {
    if (-not ([System.Management.Automation.PSTypeName]'Step9FullPower').Type) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Step9FullPower {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
    }
    try {
        [Step9FullPower]::SetThreadExecutionState([Convert]::ToUInt32("80000003", 16)) | Out-Null
    }
    catch {
        Write-Warning "Windows sleep prevention could not be enabled; continuing because it is not a strategy prerequisite: $($_.Exception.Message)"
    }
    $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Log = Join-Path $Logs "step9_full_live_morning_${Stamp}.txt"
    $StatusJson = Join-Path $Logs "step9_full_live_status_${Stamp}.json"

    function Write-Log {
        param([string]$Message)
        $Line = "{0} {1}" -f (Get-Date -Format "HH:mm:ss.fff"), $Message
        Write-Host $Line
        Add-Content -Path $Log -Value $Line -Encoding utf8
    }

    function Invoke-PythonLogged {
        param([string[]]$Arguments, [string]$Label)
        Write-Log "START $Label"

        # Windows PowerShell 5.1 can turn harmless native STDERR output into a
        # terminating NativeCommandError when the outer script uses Stop.
        # Capture both streams while temporarily allowing the native process
        # to finish, then decide success strictly from its real exit code.
        $PreviousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $Output = @(& $Python @Arguments 2>&1)
            $ExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousErrorActionPreference
        }

        @($Output) | ForEach-Object {
            $Line = [string]$_
            Write-Host $Line
            Add-Content -Path $Log -Value $Line -Encoding utf8
        }
        Write-Log "END $Label EXIT=$ExitCode"
        if ($ExitCode -ne 0) {
            throw "$Label failed with exit code $ExitCode. See log: $Log"
        }
    }

    function Get-ChainStatus {
        Invoke-PythonLogged -Label "READ-ONLY CHAIN STATUS" -Arguments @(
            "tools/check_step9_full_morning_chain_v1.py", "status", "--date", $Date, "--json-out", $StatusJson
        )
        return (Get-Content $StatusJson -Raw | ConvertFrom-Json)
    }

    function Verify-Stage {
        param([string]$Stage)
        Invoke-PythonLogged -Label "VERIFY $($Stage.ToUpper())" -Arguments @(
            "tools/check_step9_full_morning_chain_v1.py", "verify", "--date", $Date, "--stage", $Stage, "--json-out", $StatusJson
        )
    }

    Write-Log "FULL STEP 9 MORNING WRAPPER STARTED FOR $Date"
    while ((Get-Date) -lt $CollectorStart) { Start-Sleep -Milliseconds 100 }

    $Initial = Get-ChainStatus
    if (-not [bool]$Initial.step9i.sealed) {
        Invoke-PythonLogged -Label "STEP 9I DATA COLLECTION" -Arguments @(
            "-m", "RegimeTrading.scripts.collect_step9i_shadow_data", "--days", "$CollectorDays", "--interval", "5m", "--skip-bootstrap"
        )
        $AfterCollection = Get-ChainStatus
        if (-not [bool]$AfterCollection.prices.ready) {
            throw "Collector completed, but today's bars through 09:40 are not ready. Do not seal Step 9I."
        }
        Invoke-PythonLogged -Label "STEP 9I V2 MORNING SEAL" -Arguments @(
            "-m", "RegimeTrading.scripts.step9i_v2_core5_plus_holdout18_shadow_router", "morning", "--date", $Date
        )
    } else {
        Write-Log "STEP 9I already sealed and will not be rerun."
    }
    Verify-Stage "step9i"

    $State = Get-ChainStatus
    if (-not [bool]$State.step9l.sealed) {
        Invoke-PythonLogged -Label "STEP 9L V3 MORNING SEAL" -Arguments @(
            "-m", "RegimeTrading.scripts.step9l_v3_selected_strategy_shadow_engine", "morning", "--date", $Date
        )
    } else {
        Write-Log "STEP 9L already sealed and will not be rerun."
    }
    Verify-Stage "step9l"

    $State = Get-ChainStatus
    if (-not [bool]$State.step9s.sealed) {
        Invoke-PythonLogged -Label "STEP 9S PROSPECTIVE BENCHMARK ASSIGNMENT" -Arguments @(
            "-m", "RegimeTrading.scripts.step9s_prospective_contingency_shadow_v1", "morning", "--date", $Date
        )
    } else {
        Write-Log "STEP 9S already sealed and will not be rerun."
    }
    Verify-Stage "step9s"

    $State = Get-ChainStatus
    if (-not [bool]$State.step9r.sealed) {
        Invoke-PythonLogged -Label "STEP 9R V1.1 PROSPECTIVE RANKING" -Arguments @(
            "-m", "RegimeTrading.scripts.step9r_v1_candidate_ranking_research", "morning", "--date", $Date
        )
    } else {
        Write-Log "STEP 9R already sealed and will not be rerun."
    }
    Verify-Stage "upstream"

    if ((Get-Date) -gt $Step9TUDeadline) {
        throw "Upstream chain passed, but the safe Step 9T/9U wrapper start deadline 09:48:45 passed. Do not reconstruct Step 9T/9U."
    }

    $State = Get-ChainStatus
    if ([bool]$State.step9t.sealed -or [bool]$State.step9u.sealed) {
        throw "Step 9T or Step 9U is already sealed. Do not rerun them from the full wrapper."
    }

    while ((Get-Date) -lt $Step9TULaunchEarliest) { Start-Sleep -Milliseconds 100 }
    Write-Log "HANDOFF TO CONTROLLED STEP 9T -> STEP 9U LIVE WRAPPER"
    & (Join-Path $Root "run_step9tu_live_morning_v1.ps1") -Date $Date
    if ($LASTEXITCODE -ne 0) { throw "Step 9T/9U live wrapper failed with exit code $LASTEXITCODE." }

    $QStatus = "PASSED"
    try {
        Invoke-PythonLogged -Label "STEP 9Q READ-ONLY SNAPSHOT" -Arguments @(
            "-m", "RegimeTrading.scripts.step9q_powerbi_excel_feed", "--date", $Date, "--require-both-engines"
        )
    } catch {
        $QStatus = "FAILED_RETRY_ONLY_STEP9Q"
        Write-Warning "Step 9Q reporting failed after all immutable morning ledgers were safely sealed. Do not rerun any engine. Close Excel and retry only .\run_step9q_powerbi_snapshot.ps1 -Date `"$Date`" -RequireBothEngines. Error: $($_.Exception.Message)"
    }

    $Final = Get-ChainStatus
    Write-Host ""
    Write-Host "STEP9_FULL_LIVE_MORNING_V1: PASSED"
    Write-Host "DATE: $Date"
    Write-Host "PRIMARY REGIME: $($Final.step9l.primary_regime)"
    Write-Host "STEP 9R CANDIDATES / SELECTED: $($Final.step9r.candidate_rows) / $($Final.step9r.selected_rows)"
    Write-Host "STEP 9U SELECTED: $($Final.step9u.selected_count)"
    Write-Host "STEP 9Q STATUS: $QStatus"
    Write-Host "Log: $Log"
    Write-Host "DO NOT RERUN ANY SEALED MORNING ENGINE TODAY."
    Write-Host "STEP 9S MANDATORY BENCHMARK CONTROL: TRUE"
    Write-Host "STEP 9U MANDATORY CONTROL: FALSE"
    Write-Host "ROUTER ACTIVE: FALSE"
    Write-Host "NO ORDER WAS SENT"
}
catch {
    Write-Host ""
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "FULL MORNING WRAPPER STOPPED AT THE FAILED STAGE."
    Write-Host "Do not rerun any stage already reported as sealed."
    Write-Host "Retry only the failed downstream stage while its deadline remains open."
    throw
}
finally {
    try { [Step9FullPower]::SetThreadExecutionState([Convert]::ToUInt32("80000000", 16)) | Out-Null } catch {}
    try { $Mutex.ReleaseMutex() } catch {}
    $Mutex.Dispose()
}



