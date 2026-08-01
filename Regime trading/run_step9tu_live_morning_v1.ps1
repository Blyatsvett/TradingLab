param(
    [string]$Date = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if (-not $Date) { $Date = (Get-Date).ToString("yyyy-MM-dd") }

if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Project virtual-environment Python is missing: $Python"
}
if ((Get-Date).ToString("yyyy-MM-dd") -ne $Date) {
    throw "Live morning seal may only run for today's date. Requested=$Date, today=$((Get-Date).ToString('yyyy-MM-dd'))."
}

$Now = Get-Date
$LaunchEarliest = Get-Date -Hour 9 -Minute 47 -Second 35
$LatestStart = Get-Date -Hour 9 -Minute 48 -Second 45
$Step9TStart = Get-Date -Hour 9 -Minute 48 -Second 0
$Step9UStart = Get-Date -Hour 9 -Minute 48 -Second 5
$Step9UDeadline = Get-Date -Hour 9 -Minute 49 -Second 55
if ($Now -lt $LaunchEarliest) {
    throw "Launch this wrapper no earlier than 09:47:35. Current time: $($Now.ToString('HH:mm:ss'))."
}
if ($Now -gt $LatestStart) {
    throw "Safe wrapper start deadline 09:48:45 has passed. Do not reconstruct the session. Current time: $($Now.ToString('HH:mm:ss'))."
}

$Offset = [TimeZoneInfo]::Local.GetUtcOffset($Now)
if ($Offset.TotalHours -ne 2) {
    throw "Expected Stockholm summer-time offset +02:00; current local offset is $Offset."
}

$MutexName = "STEP9TU_MORNING_$($Date.Replace('-', ''))"
$Mutex = [System.Threading.Mutex]::new($false, $MutexName)
if (-not $Mutex.WaitOne(0)) {
    $Mutex.Dispose()
    throw "Another Step 9T -> Step 9U morning wrapper is already running. Do not double-click."
}

$SleepTypeAdded = $false
try {
    if (-not ([System.Management.Automation.PSTypeName]'Step9TU_Power').Type) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Step9TU_Power {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
        $SleepTypeAdded = $true
    }
    try {
        [Step9TU_Power]::SetThreadExecutionState([Convert]::ToUInt32("80000003", 16)) | Out-Null
    }
    catch {
        Write-Warning "Windows sleep prevention could not be enabled; continuing because it is not a strategy prerequisite: $($_.Exception.Message)"
    }
    $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Log = Join-Path $Logs "step9tu_live_morning_${Stamp}.txt"
    $Preview = Join-Path $Logs "step9tu_live_preview_${Stamp}.json"
    $Verified = Join-Path $Logs "step9tu_live_verified_${Stamp}.json"

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

    Write-Log "STEP9TU LIVE MORNING WRAPPER STARTED FOR $Date"
    Write-Log "Read-only exact preview begins."
    Invoke-PythonLogged -Label "READ-ONLY PREVIEW" -Arguments @(
        "tools/check_step9tu_morning_readiness_v1.py", "readiness",
        "--date", $Date,
        "--json-out", $Preview
    )

    while ((Get-Date) -lt $Step9TStart) {
        Start-Sleep -Milliseconds 100
    }
    if ((Get-Date) -gt (Get-Date -Hour 9 -Minute 49 -Second 10)) {
        throw "Insufficient safe time remains to start Step 9T. Do not reconstruct the session."
    }

    Invoke-PythonLogged -Label "STEP 9T PROSPECTIVE MORNING SEAL" -Arguments @(
        "-m", "RegimeTrading.scripts.step9t_prospective_regime_transition_archetype_v1",
        "morning",
        "--date", $Date,
        "--ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db"
    )

    while ((Get-Date) -lt $Step9UStart) {
        Start-Sleep -Milliseconds 100
    }
    if ((Get-Date) -gt $Step9UDeadline) {
        throw "Step 9T sealed, but Step 9U deadline 09:49:55 passed. Do not rerun Step 9T."
    }

    Invoke-PythonLogged -Label "STEP 9U PROSPECTIVE MORNING SEAL" -Arguments @(
        "-m", "RegimeTrading.scripts.step9u_prospective_contingency_selector_v1",
        "morning",
        "--date", $Date,
        "--step9t-ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db",
        "--ledger-db", "data\step9u_contingency_selector_prospective_shadow_v1.db"
    )

    Invoke-PythonLogged -Label "POST-SEAL EXACT VERIFICATION" -Arguments @(
        "tools/check_step9tu_morning_readiness_v1.py", "verify-sealed",
        "--date", $Date,
        "--preview-json", $Preview,
        "--json-out", $Verified
    )

    $Result = Get-Content $Verified -Raw | ConvertFrom-Json
    Write-Log "STEP9TU LIVE MORNING SEAL VERIFIED"
    Write-Host ""
    Write-Host "STEP9TU_LIVE_MORNING_V1: PASSED"
    Write-Host "DATE: $Date"
    Write-Host "REGIME / TRANSITION: $($Result.source_regime) / $($Result.transition_state)"
    Write-Host "CANDIDATES / SELECTABLE / SELECTED: $($Result.directional_candidates) / $($Result.selectable_candidates) / $($Result.selected_count)"
    Write-Host "SELECTED TICKERS: $(if (@($Result.selected_tickers).Count -gt 0) { $Result.selected_tickers -join ' | ' } else { 'NONE' })"
    Write-Host "Log: $Log"
    Write-Host "Verified JSON: $Verified"
    Write-Host "DO NOT RUN STEP 9T OR STEP 9U MORNING AGAIN TODAY."
    Write-Host "MANDATORY CONTROL ACTIVE: FALSE"
    Write-Host "ROUTER ACTIVE: FALSE"
    Write-Host "NO ORDER WAS SENT"
}
catch {
    Write-Host ""
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "MORNING WRAPPER STOPPED SAFELY."
    Write-Host "Do not rerun any upstream sealed engine."
    Write-Host "If Step 9T succeeded but Step 9U failed, retry only Step 9U before 09:49:55."
    Write-Host "If Step 9U succeeded but verification failed, do not rerun either engine; inspect the log."
    throw
}
finally {
    try { [Step9TU_Power]::SetThreadExecutionState([Convert]::ToUInt32("80000000", 16)) | Out-Null } catch {}
    try { $Mutex.ReleaseMutex() } catch {}
    $Mutex.Dispose()
}



