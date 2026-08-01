param(
    [string]$Date = "",
    [ValidateSet("PRIMARY", "WATCHDOG", "MANUAL")]
    [string]$InvocationRole = "MANUAL",
    [ValidateRange(1, 10)]
    [int]$CollectorDays = 2,
    [ValidateRange(1, 5)]
    [int]$CollectorMaxAttempts = 3,
    [ValidateRange(1, 60)]
    [int]$CollectorRetrySeconds = 8,
    [ValidateRange(30, 900)]
    [int]$StageTimeoutSeconds = 360,
    [ValidateRange(30, 600)]
    [int]$CommandTimeoutSeconds = 180,
    [ValidateRange(5, 120)]
    [int]$EmergencyDrainSeconds = 20,
    [ValidateRange(30, 14400)]
    [int]$WatchdogMutexWaitSeconds = 10800,
    [switch]$NoMockFallback,
    [string]$MockBaseRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Support = Join-Path $Root "tools\step9_morning_v2_support.py"
$StageModule = "RegimeTrading.scripts.step9_morning_v2_stage_runner"
$Fallback = Join-Path $Root "run_step9_morning_mock_fallback_v2.ps1"
$RuntimeManifest = Join-Path $Root "config\step9_morning_v2_runtime_manifest.json"
$Logs = Join-Path $Root "logs"
$RegistryRoot = Join-Path $Root "data\prospective_session_registry"

try {
    $StockholmZone = [TimeZoneInfo]::FindSystemTimeZoneById("W. Europe Standard Time")
}
catch {
    $StockholmZone = $null
}

if (-not $Date) {
    if ($null -ne $StockholmZone) {
        $Date = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $StockholmZone).ToString("yyyy-MM-dd")
    }
    else {
        $Date = (Get-Date).ToString("yyyy-MM-dd")
    }
}
if (-not $MockBaseRoot) {
    $MockBaseRoot = Join-Path $env:USERPROFILE "S9M"
}

$SafeDate = $Date -replace "[^0-9]", ""
if ([string]::IsNullOrWhiteSpace($SafeDate)) {
    $SafeDate = "INVALID_DATE"
}
$Stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd_HHmmss_fff")
$RunId = "{0}_{1}_{2}" -f $Stamp, $PID, ([Guid]::NewGuid().ToString("N").Substring(0, 8))
$RegistryDir = Join-Path $RegistryRoot $SafeDate
$Log = Join-Path $Logs "step9_full_live_morning_v2_${RunId}.txt"
$StatusJson = Join-Path $Logs "step9_full_live_morning_v2_status_${RunId}.json"
$RegistryPath = Join-Path $RegistryDir "STEP9_MORNING_V2_RUN_${RunId}.json"
$RuntimeCheckJson = Join-Path $Logs "step9_morning_v2_runtime_${RunId}.json"
$SnapshotDir = Join-Path $Root "data\step9_morning_v2_snapshots\$Date"
$Snapshot0940 = Join-Path $SnapshotDir "prices_through_0940.db"
$Snapshot0945 = Join-Path $SnapshotDir "prices_through_0945.db"
$Snapshot0940Rel = "data\step9_morning_v2_snapshots\$Date\prices_through_0940.db"
$Snapshot0945Rel = "data\step9_morning_v2_snapshots\$Date\prices_through_0945.db"
$RawPriceDb = Join-Path $Root "data\step9i_shadow_intraday_prices.db"

New-Item -ItemType Directory -Path $Logs -Force | Out-Null
New-Item -ItemType Directory -Path $RegistryDir -Force | Out-Null

$StageFailures = [ordered]@{}
$StageTimings = [ordered]@{}
$CollectorHistory = New-Object System.Collections.ArrayList
$ActiveJobs = New-Object System.Collections.ArrayList
$SnapshotResults = [ordered]@{}
$RuntimeManifestResult = $null
$FatalError = ""
$FallbackResult = $null
$LiveStatus = $null
$LiveAccepted = $false
$RuntimeValidated = $false
$SupportUsable = $false
$FallbackSafe = $true
$SuppressFallback = $false
$SuppressFallbackReason = ""
$Mutex = $null
$MutexOwned = $false
$MutexState = "NOT_ATTEMPTED"
$MutexAbandoned = $false
$WatchdogObservedPriorOwner = $false
$PowerStateEnabled = $false
$LocationChanged = $false
$PreviousLocation = Get-Location
$NativeInvocationCounter = 0
$RegistryWritten = $false

function Get-StockholmNow {
    if ($null -eq $script:StockholmZone) {
        return [DateTimeOffset]::UtcNow
    }
    return [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $script:StockholmZone)
}

function New-StockholmMoment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SessionDate,
        [Parameter(Mandatory = $true)]
        [string]$Clock
    )
    $Local = [datetime]::ParseExact(
        "$SessionDate $Clock",
        "yyyy-MM-dd HH:mm:ss",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None
    )
    $Local = [datetime]::SpecifyKind($Local, [DateTimeKind]::Unspecified)
    if ($script:StockholmZone.IsInvalidTime($Local)) {
        throw "Stockholm time is invalid because of a daylight-saving transition: $SessionDate $Clock"
    }
    if ($script:StockholmZone.IsAmbiguousTime($Local)) {
        throw "Stockholm time is ambiguous because of a daylight-saving transition: $SessionDate $Clock"
    }
    $Offset = $script:StockholmZone.GetUtcOffset($Local)
    return New-Object DateTimeOffset($Local, $Offset)
}

function Get-ObjectField {
    param(
        [object]$InputObject,
        [string]$Name,
        [object]$Default = $null
    )
    if ($null -eq $InputObject) {
        return $Default
    }
    if ($InputObject -is [Collections.IDictionary]) {
        if ($InputObject.Contains($Name)) {
            return $InputObject[$Name]
        }
        return $Default
    }
    $Property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $Property) {
        return $Default
    }
    return $Property.Value
}

function Add-FatalError {
    param([string]$Message)
    if ([string]::IsNullOrWhiteSpace($Message)) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($script:FatalError)) {
        $script:FatalError = $Message
    }
    else {
        $script:FatalError = "$($script:FatalError) | $Message"
    }
}

function Write-Log {
    param([string]$Message)
    $Clock = (Get-StockholmNow).ToString("HH:mm:ss.fff")
    $Line = "{0} {1}" -f $Clock, $Message
    Write-Host $Line
    Add-Content -LiteralPath $script:Log -Value $Line -Encoding UTF8
}

function Wait-UntilStockholm {
    param([DateTimeOffset]$Target)
    while ((Get-StockholmNow) -lt $Target) {
        Start-Sleep -Milliseconds 100
    }
}

function ConvertTo-WindowsCommandLineArgument {
    param(
        [AllowNull()]
        [AllowEmptyString()]
        [string]$Argument
    )
    if ($null -eq $Argument) {
        $Argument = ""
    }
    if ($Argument.Length -gt 0 -and $Argument -notmatch "[\s`"]") {
        return $Argument
    }

    $Builder = New-Object Text.StringBuilder
    [void]$Builder.Append([char]34)
    $Backslashes = 0
    for ($Index = 0; $Index -lt $Argument.Length; $Index++) {
        $Character = $Argument[$Index]
        if ($Character -eq [char]92) {
            $Backslashes++
            continue
        }
        if ($Character -eq [char]34) {
            if ($Backslashes -gt 0) {
                [void]$Builder.Append(("\" * ($Backslashes * 2)))
            }
            [void]$Builder.Append("\")
            [void]$Builder.Append([char]34)
            $Backslashes = 0
            continue
        }
        if ($Backslashes -gt 0) {
            [void]$Builder.Append(("\" * $Backslashes))
            $Backslashes = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($Backslashes -gt 0) {
        [void]$Builder.Append(("\" * ($Backslashes * 2)))
    }
    [void]$Builder.Append([char]34)
    return $Builder.ToString()
}

function Join-WindowsCommandLine {
    param([string[]]$Arguments)
    $Quoted = @(
        foreach ($Argument in $Arguments) {
            ConvertTo-WindowsCommandLineArgument -Argument ([string]$Argument)
        }
    )
    return ($Quoted -join " ")
}

function Read-ProcessOutput {
    param(
        [string]$StdOut,
        [string]$StdErr
    )
    foreach ($Path in @($StdOut, $StdErr)) {
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            foreach ($OutputLine in @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
                if (-not [string]::IsNullOrWhiteSpace([string]$OutputLine)) {
                    Write-Host ([string]$OutputLine)
                    Add-Content -LiteralPath $script:Log -Value ([string]$OutputLine) -Encoding UTF8
                }
            }
        }
    }
}

function Stop-BoundedProcess {
    param(
        [Diagnostics.Process]$Process,
        [string]$Label
    )
    try {
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction Stop
        }
        if (-not $Process.WaitForExit(10000)) {
            $script:FallbackSafe = $false
            throw "$Label process $($Process.Id) did not terminate after Stop-Process."
        }
    }
    catch {
        $script:FallbackSafe = $false
        throw
    }
}

function Invoke-PythonLogged {
    param(
        [string[]]$Arguments,
        [string]$Label,
        [int]$TimeoutSeconds = $script:CommandTimeoutSeconds,
        [switch]$NonCritical
    )
    $script:NativeInvocationCounter++
    $Token = ($Label -replace "[^A-Za-z0-9]+", "_").Trim("_").ToLower()
    if ([string]::IsNullOrWhiteSpace($Token)) {
        $Token = "python"
    }
    $Out = Join-Path $script:Logs ("step9_morning_v2_cmd_{0:D3}_{1}_{2}.stdout.txt" -f $script:NativeInvocationCounter, $Token, $script:RunId)
    $Err = Join-Path $script:Logs ("step9_morning_v2_cmd_{0:D3}_{1}_{2}.stderr.txt" -f $script:NativeInvocationCounter, $Token, $script:RunId)
    $CommandLine = Join-WindowsCommandLine -Arguments $Arguments

    Write-Log "START $Label"
    $StartedAt = Get-StockholmNow
    $Process = Start-Process `
        -FilePath $script:Python `
        -WorkingDirectory $script:Root `
        -ArgumentList $CommandLine `
        -RedirectStandardOutput $Out `
        -RedirectStandardError $Err `
        -WindowStyle Hidden `
        -PassThru

    $TimedOut = $false
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        $TimedOut = $true
        try {
            Stop-BoundedProcess -Process $Process -Label $Label
        }
        catch {
            Read-ProcessOutput -StdOut $Out -StdErr $Err
            throw
        }
    }
    Read-ProcessOutput -StdOut $Out -StdErr $Err
    $Duration = [math]::Round(((Get-StockholmNow) - $StartedAt).TotalSeconds, 3)

    if ($TimedOut) {
        Write-Log "END $Label TIMEOUT=TRUE DURATION_SECONDS=$Duration"
        if ($NonCritical) {
            Write-Warning "$Label exceeded its $TimeoutSeconds second timeout."
            return $false
        }
        throw "$Label exceeded its $TimeoutSeconds second timeout."
    }

    $ExitCode = $Process.ExitCode
    Write-Log "END $Label EXIT=$ExitCode DURATION_SECONDS=$Duration"
    if ($ExitCode -ne 0) {
        if ($NonCritical) {
            Write-Warning "$Label failed with exit code $ExitCode. Sealed morning ledgers remain authoritative."
            return $false
        }
        throw "$Label failed with exit code $ExitCode. See $Log"
    }
    return $true
}

function Get-LiveStatus {
    Invoke-PythonLogged -Label "LIGHTWEIGHT LIVE STATUS" -TimeoutSeconds 60 -Arguments @(
        $script:Support,
        "status",
        "--date",
        $script:Date,
        "--json-out",
        $script:StatusJson
    ) | Out-Null
    return (Get-Content -LiteralPath $script:StatusJson -Raw | ConvertFrom-Json)
}

function Verify-LiveStage {
    param([string]$Stage)
    $VerifyJson = Join-Path $script:Logs "step9_morning_v2_verify_${Stage}_$($script:RunId).json"
    try {
        Invoke-PythonLogged -Label "VERIFY $($Stage.ToUpper())" -TimeoutSeconds 90 -Arguments @(
            $script:Support,
            "verify",
            "--date",
            $script:Date,
            "--stage",
            $Stage,
            "--json-out",
            $VerifyJson
        ) | Out-Null
        $Verified = Get-Content -LiteralPath $VerifyJson -Raw | ConvertFrom-Json
        if ((Get-ObjectField -InputObject $Verified -Name "verification" -Default "") -ne "PASSED") {
            throw "Canonical verification did not report PASSED for $Stage."
        }
        return $Verified
    }
    catch {
        $script:FallbackSafe = $false
        throw
    }
}

function Verify-AllLiveStages {
    $VerifyJson = Join-Path $script:Logs "step9_morning_v2_verify_all_$($script:RunId).json"
    try {
        Invoke-PythonLogged -Label "CANONICAL VERIFY ALL LIVE STAGES" -TimeoutSeconds 120 -Arguments @(
            $script:Support,
            "verify",
            "--date",
            $script:Date,
            "--stage",
            "all",
            "--json-out",
            $VerifyJson
        ) | Out-Null
        $Verified = Get-Content -LiteralPath $VerifyJson -Raw | ConvertFrom-Json
        if ((Get-ObjectField -InputObject $Verified -Name "verification" -Default "") -ne "PASSED") {
            throw "Canonical full-chain verification did not report PASSED."
        }
        if (-not [bool](Get-ObjectField -InputObject $Verified -Name "live_complete" -Default $false)) {
            throw "Canonical full-chain verification did not report a complete live chain."
        }
        return $Verified
    }
    catch {
        $script:FallbackSafe = $false
        throw
    }
}

function Start-StageProcess {
    param(
        [string]$Stage,
        [string[]]$Arguments
    )
    $Out = Join-Path $script:Logs "step9_morning_v2_${Stage}_$($script:RunId).stdout.txt"
    $Err = Join-Path $script:Logs "step9_morning_v2_${Stage}_$($script:RunId).stderr.txt"
    $Json = Join-Path $script:Logs "step9_morning_v2_${Stage}_$($script:RunId).json"
    $AllArguments = @("-m", $script:StageModule, $Stage) + $Arguments + @("--json-out", $Json)
    $CommandLine = Join-WindowsCommandLine -Arguments $AllArguments

    Write-Log "START $($Stage.ToUpper()) ASYNC"
    $StartedAt = Get-StockholmNow
    $Process = Start-Process `
        -FilePath $script:Python `
        -WorkingDirectory $script:Root `
        -ArgumentList $CommandLine `
        -RedirectStandardOutput $Out `
        -RedirectStandardError $Err `
        -WindowStyle Hidden `
        -PassThru

    $Job = [PSCustomObject]@{
        Stage = $Stage
        Process = $Process
        StdOut = $Out
        StdErr = $Err
        Json = $Json
        StartedAt = $StartedAt
        Completed = $false
        OutputDrained = $false
        Success = $false
    }
    [void]$script:ActiveJobs.Add($Job)
    Write-Log "STARTED $($Stage.ToUpper()) PID=$($Process.Id)"
    return $Job
}

function Drain-StageOutput {
    param([pscustomobject]$Job)
    if ([bool]$Job.OutputDrained) {
        return
    }
    Read-ProcessOutput -StdOut $Job.StdOut -StdErr $Job.StdErr
    $Job.OutputDrained = $true
}

function Finish-StageProcess {
    param(
        [pscustomobject]$Job,
        [int]$TimeoutSeconds = $script:StageTimeoutSeconds
    )
    if ([bool]$Job.Completed) {
        return [bool]$Job.Success
    }

    $ElapsedBeforeWait = ((Get-StockholmNow) - $Job.StartedAt).TotalSeconds
    $RemainingMilliseconds = [math]::Max(
        0,
        [math]::Floor(($TimeoutSeconds - $ElapsedBeforeWait) * 1000)
    )
    $TimedOut = $false
    if (-not $Job.Process.WaitForExit([int]$RemainingMilliseconds)) {
        $TimedOut = $true
        try {
            Stop-BoundedProcess -Process $Job.Process -Label $Job.Stage
        }
        catch {
            $script:StageFailures[$Job.Stage] = "PROCESS_COULD_NOT_BE_TERMINATED"
        }
    }

    $EndedAt = Get-StockholmNow
    try {
        if ($Job.Process.HasExited) {
            $EndedAt = [DateTimeOffset]$Job.Process.ExitTime
        }
    }
    catch {}
    $Duration = [math]::Round(($EndedAt - $Job.StartedAt).TotalSeconds, 3)
    $script:StageTimings[$Job.Stage] = $Duration
    Drain-StageOutput -Job $Job
    $Job.Completed = $true

    if ($TimedOut) {
        $script:StageFailures[$Job.Stage] = "TIMEOUT_${TimeoutSeconds}_SECONDS"
        Write-Log "END $($Job.Stage.ToUpper()) ASYNC TIMEOUT=TRUE DURATION_SECONDS=$Duration"
        return $false
    }
    if (-not $Job.Process.HasExited) {
        $script:StageFailures[$Job.Stage] = "PROCESS_STILL_RUNNING"
        Write-Log "END $($Job.Stage.ToUpper()) ASYNC PROCESS_STILL_RUNNING"
        return $false
    }

    $ExitCode = $Job.Process.ExitCode
    Write-Log "END $($Job.Stage.ToUpper()) ASYNC EXIT=$ExitCode DURATION_SECONDS=$Duration"
    if ($ExitCode -ne 0) {
        $script:StageFailures[$Job.Stage] = "EXIT_$ExitCode"
        return $false
    }

    try {
        [void](Verify-LiveStage -Stage $Job.Stage)
        $Job.Success = $true
        return $true
    }
    catch {
        $script:StageFailures[$Job.Stage] = $_.Exception.Message
        Write-Log "VERIFY FAILURE $($Job.Stage.ToUpper()): $($_.Exception.Message)"
        return $false
    }
}

function Stop-AndDrainAllStageProcesses {
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($script:EmergencyDrainSeconds)
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        $Running = @(
            $script:ActiveJobs | Where-Object {
                -not [bool]$_.Completed -and -not $_.Process.HasExited
            }
        )
        if ($Running.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 200
    }

    foreach ($Job in @($script:ActiveJobs)) {
        if ([bool]$Job.Completed) {
            continue
        }
        try {
            if (-not $Job.Process.HasExited) {
                Write-Log "EMERGENCY STOP $($Job.Stage.ToUpper()) PID=$($Job.Process.Id)"
                Stop-BoundedProcess -Process $Job.Process -Label $Job.Stage
                $script:StageFailures[$Job.Stage] = "EMERGENCY_TERMINATION_AFTER_LIVE_ERROR"
            }
            elseif ($Job.Process.ExitCode -ne 0) {
                $script:StageFailures[$Job.Stage] = "EXIT_$($Job.Process.ExitCode)"
            }
        }
        catch {
            Add-FatalError -Message "STAGE_DRAIN_ERROR $($Job.Stage): $($_.Exception.Message)"
        }
        finally {
            Drain-StageOutput -Job $Job
            $Job.Completed = $true
        }
    }
}

function Get-OrphanedSessionChildProcesses {
    $ExpectedPython = [IO.Path]::GetFullPath($script:Python)
    $SupportNeedle = [IO.Path]::GetFullPath($script:Support)
    $PriceDbNeedle = [IO.Path]::GetFullPath($script:RawPriceDb)
    $LiveStageJsonNeedle = Join-Path ([IO.Path]::GetFullPath($script:Logs)) (
        "step9_morning_v2_"
    )
    $SessionDateNeedle = [string]$script:Date
    $CollectorModule = "RegimeTrading.scripts.collect_step9i_shadow_data"
    $MockBaseNeedle = [IO.Path]::GetFullPath($script:MockBaseRoot)
    $MockSessionPrefix = Join-Path $MockBaseNeedle (
        "MOCK_{0}_MORNING_V2_FALLBACK_" -f $script:SafeDate
    )
    $Candidates = @(
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
            Where-Object {
                $Executable = [string]$_.ExecutablePath
                $CommandLine = [string]$_.CommandLine
                $IsStageRunner = (
                    $CommandLine.IndexOf(
                        $script:StageModule,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0 -and
                    $CommandLine.IndexOf(
                        $LiveStageJsonNeedle,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0 -and
                    $CommandLine.IndexOf(
                        $SessionDateNeedle,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0
                )
                $IsCollector = (
                    $CommandLine.IndexOf(
                        $CollectorModule,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0 -and
                    $CommandLine.IndexOf(
                        $PriceDbNeedle,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0
                )
                $IsSupportCommand = (
                    $CommandLine.IndexOf(
                        $SupportNeedle,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0 -and
                    $CommandLine.IndexOf(
                        $SessionDateNeedle,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0
                )
                $IsSameSessionMock = (
                    $CommandLine.IndexOf(
                        $MockSessionPrefix,
                        [StringComparison]::OrdinalIgnoreCase
                    ) -ge 0
                )
                -not [string]::IsNullOrWhiteSpace($Executable) -and
                [string]::Equals(
                    [IO.Path]::GetFullPath($Executable),
                    $ExpectedPython,
                    [StringComparison]::OrdinalIgnoreCase
                ) -and
                (
                    $IsStageRunner -or
                    $IsCollector -or
                    $IsSupportCommand -or
                    $IsSameSessionMock
                )
            }
    )
    return $Candidates
}

function Stop-VerifiedSessionChildProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Reason
    )

    $Candidates = @(Get-OrphanedSessionChildProcesses)
    if ($Candidates.Count -eq 0) {
        Write-Log "NO ORPHANED LIVE OR SAME-SESSION MOCK CHILD PROCESS FOUND"
        return
    }

    Write-Log (
        "WAITING FOR VERIFIED ORPHANED SESSION CHILDREN BEFORE ${Reason}: PIDS={0}" -f
        ($Candidates.ProcessId -join ",")
    )
    Start-Sleep -Seconds ([math]::Min(5, $script:EmergencyDrainSeconds))

    $Candidates = @(Get-OrphanedSessionChildProcesses)
    foreach ($Candidate in $Candidates) {
        $CandidatePid = [int]$Candidate.ProcessId
        if ($null -eq (Get-Process -Id $CandidatePid -ErrorAction SilentlyContinue)) {
            continue
        }
        Write-Log (
            "TERMINATING VERIFIED ORPHANED SESSION CHILD PID=$CandidatePid REASON=$Reason"
        )
        Stop-Process -Id $CandidatePid -Force -ErrorAction Stop
    }

    Start-Sleep -Seconds 2
    $Remaining = @(Get-OrphanedSessionChildProcesses)
    if ($Remaining.Count -gt 0) {
        $script:FallbackSafe = $false
        throw (
            "Verified orphaned session child processes could not be terminated: {0}" -f
            ($Remaining.ProcessId -join ", ")
        )
    }
}

function Stop-OrphanedProcessesAfterAbandonment {
    if (-not $script:MutexAbandoned) {
        return
    }
    Write-Log (
        "WATCHDOG ACQUIRED AN ABANDONED MUTEX; CHECKING FOR ORPHANED LIVE " +
        "OR SAME-SESSION MOCK CHILDREN"
    )
    try {
        Stop-VerifiedSessionChildProcesses -Reason "ABANDONED_MUTEX_RECOVERY"
    }
    catch {
        $script:FallbackSafe = $false
        throw "Could not prove orphan-process safety after abandoned mutex: $($_.Exception.Message)"
    }
}

function Assert-NoLiveStageProcessBeforeFallback {
    try {
        Stop-VerifiedSessionChildProcesses -Reason "NEW_MOCK_FALLBACK"
    }
    catch {
        $script:FallbackSafe = $false
        throw (
            "Could not drain live or same-session mock child processes before fallback: " +
            $_.Exception.Message
        )
    }
}

function Test-PriceReadiness {
    param([object]$Status)
    $Prices = Get-ObjectField -InputObject $Status -Name "prices"
    if ($null -eq $Prices) {
        return $false
    }
    return (
        ([string](Get-ObjectField -InputObject $Prices -Name "sqlite_integrity" -Default "")).ToLower() -eq "ok" -and
        [int](Get-ObjectField -InputObject $Prices -Name "today_tickers" -Default 0) -eq 29 -and
        [bool](Get-ObjectField -InputObject $Prices -Name "ready_through_0945" -Default $false)
    )
}

function Ensure-CollectorReadiness {
    $Ready = $false
    $LastStatus = $null
    for ($Attempt = 1; $Attempt -le $script:CollectorMaxAttempts; $Attempt++) {
        $Now = Get-StockholmNow
        if ($Attempt -gt 1 -and $Now -gt $script:CollectorRetryLatestStart) {
            break
        }

        $CollectorSucceeded = Invoke-PythonLogged `
            -Label "STEP 9 MORNING DATA COLLECTION ATTEMPT $Attempt" `
            -TimeoutSeconds 120 `
            -NonCritical `
            -Arguments @(
                "-m",
                "RegimeTrading.scripts.collect_step9i_shadow_data",
                "--days",
                "$($script:CollectorDays)",
                "--interval",
                "5m",
                "--db",
                $script:RawPriceDb,
                "--skip-bootstrap"
            )

        try {
            $LastStatus = Get-LiveStatus
            $Ready = Test-PriceReadiness -Status $LastStatus
        }
        catch {
            $Ready = $false
            $script:StageFailures["collector_status_attempt_$Attempt"] = $_.Exception.Message
        }

        $Prices = Get-ObjectField -InputObject $LastStatus -Name "prices"
        [void]$script:CollectorHistory.Add([PSCustomObject]@{
            attempt = $Attempt
            completed_at_stockholm = (Get-StockholmNow).ToString("o")
            collector_exit_success = [bool]$CollectorSucceeded
            ready = [bool]$Ready
            today_tickers = [int](Get-ObjectField -InputObject $Prices -Name "today_tickers" -Default 0)
            exact_0940_tickers = [int](Get-ObjectField -InputObject $Prices -Name "exact_0940_tickers" -Default 0)
            exact_0945_tickers = [int](Get-ObjectField -InputObject $Prices -Name "exact_0945_tickers" -Default 0)
            max_datetime_today = [string](Get-ObjectField -InputObject $Prices -Name "max_datetime_today" -Default "")
        })

        if ($Ready) {
            Write-Log "PRICE READINESS PASSED ON COLLECTOR ATTEMPT $Attempt"
            return $LastStatus
        }
        if ($Attempt -lt $script:CollectorMaxAttempts -and (Get-StockholmNow) -le $script:CollectorRetryLatestStart) {
            Write-Log "PRICE READINESS INCOMPLETE AFTER ATTEMPT $Attempt; RETRYING"
            Start-Sleep -Seconds $script:CollectorRetrySeconds
        }
    }

    $Prices = Get-ObjectField -InputObject $LastStatus -Name "prices"
    throw (
        "Price readiness failed after {0} attempts: tickers={1}/29 exact0940={2}/29 exact0945={3}/29 max={4}" -f
        $script:CollectorHistory.Count,
        (Get-ObjectField -InputObject $Prices -Name "today_tickers" -Default 0),
        (Get-ObjectField -InputObject $Prices -Name "exact_0940_tickers" -Default 0),
        (Get-ObjectField -InputObject $Prices -Name "exact_0945_tickers" -Default 0),
        (Get-ObjectField -InputObject $Prices -Name "max_datetime_today" -Default "")
    )
}

function Ensure-ImmutableSnapshot {
    param(
        [string]$Cutoff,
        [string]$Destination,
        [string]$ResultJson
    )
    Invoke-PythonLogged -Label "CREATE OR VERIFY IMMUTABLE $Cutoff SNAPSHOT" -TimeoutSeconds 120 -Arguments @(
        $script:Support,
        "snapshot",
        "--source-db",
        $script:RawPriceDb,
        "--dest-db",
        $Destination,
        "--date",
        $script:Date,
        "--cutoff",
        $Cutoff,
        "--json-out",
        $ResultJson
    ) | Out-Null

    $Result = Get-Content -LiteralPath $ResultJson -Raw | ConvertFrom-Json
    if ([string](Get-ObjectField -InputObject $Result -Name "session_date" -Default "") -ne $script:Date) {
        throw "Snapshot $Cutoff result has a conflicting session date."
    }
    if ([string](Get-ObjectField -InputObject $Result -Name "cutoff" -Default "") -ne $Cutoff) {
        throw "Snapshot $Cutoff result has a conflicting cutoff."
    }
    if (([string](Get-ObjectField -InputObject $Result -Name "sqlite_integrity" -Default "")).ToLower() -ne "ok") {
        throw "Snapshot $Cutoff failed SQLite integrity validation."
    }
    if ([int](Get-ObjectField -InputObject $Result -Name "today_tickers" -Default 0) -ne 29) {
        throw "Snapshot $Cutoff does not contain exactly 29 session tickers."
    }
    if ([string](Get-ObjectField -InputObject $Result -Name "max_clock_today" -Default "") -ne $Cutoff) {
        throw "Snapshot $Cutoff has an unexpected maximum source clock."
    }
    $Hash = [string](Get-ObjectField -InputObject $Result -Name "snapshot_sha256" -Default "")
    if ($Hash -notmatch "^[a-fA-F0-9]{64}$") {
        throw "Snapshot $Cutoff did not return a valid SHA-256."
    }
    return $Result
}

function New-FailureStatus {
    param([string]$Classification = "LIVE_FAILED")
    return [PSCustomObject]@{
        session_date = $script:Date
        classification = $Classification
        live_complete = $false
        sealed_count = 0
        router_active = $false
        orders_enabled = $false
    }
}

function Get-EffectiveClassification {
    if ($script:LiveAccepted) {
        return "LIVE_COMPLETE"
    }
    $Reported = [string](Get-ObjectField -InputObject $script:LiveStatus -Name "classification" -Default "LIVE_FAILED")
    if ($Reported -eq "LIVE_COMPLETE") {
        return "LIVE_FAILED_CANONICAL_VERIFICATION"
    }
    return $Reported
}

function Write-ImmutableRegistry {
    $Status = $script:LiveStatus
    if ($null -eq $Status) {
        $Status = New-FailureStatus
    }
    $Payload = [ordered]@{
        run_id = $script:RunId
        session_date = $script:Date
        orchestrator = "STEP9_FULL_LIVE_MORNING_ORCHESTRATOR_V2"
        invocation_role = $script:InvocationRole
        created_at_stockholm = (Get-StockholmNow).ToString("o")
        registry_immutable = $true
        live_classification = Get-EffectiveClassification
        live_complete = [bool]$script:LiveAccepted
        live_canonical_verification = [bool]$script:LiveAccepted
        reported_sealed_count = [int](Get-ObjectField -InputObject $Status -Name "sealed_count" -Default 0)
        stage_status = $Status
        stage_failures = $script:StageFailures
        stage_timings_seconds = $script:StageTimings
        collector_attempts = @($script:CollectorHistory)
        snapshot_results = $script:SnapshotResults
        runtime_manifest = $script:RuntimeManifestResult
        runtime_manifest_validated = [bool]$script:RuntimeValidated
        mutex_state = $script:MutexState
        mutex_abandoned_takeover = [bool]$script:MutexAbandoned
        fatal_error = $script:FatalError
        snapshot_0940 = $script:Snapshot0940
        snapshot_0945 = $script:Snapshot0945
        mock_fallback_requested = (-not $script:NoMockFallback.IsPresent)
        mock_fallback_suppressed = [bool]$script:SuppressFallback
        mock_fallback_suppression_reason = $script:SuppressFallbackReason
        mock_fallback_safe = [bool]$script:FallbackSafe
        mock_fallback_result = $script:FallbackResult
        router_active = $false
        orders_enabled = $false
        real_mock_ledger_merge = "PROHIBITED"
    }
    if (Test-Path -LiteralPath $script:RegistryPath) {
        throw "Immutable per-run registry already exists: $($script:RegistryPath)"
    }
    $Temp = "$($script:RegistryPath).$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $Payload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $Temp -Encoding UTF8
        [IO.File]::Move($Temp, $script:RegistryPath)
        $script:RegistryWritten = $true
    }
    finally {
        if (Test-Path -LiteralPath $Temp -PathType Leaf) {
            Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
    Set-Location -LiteralPath $Root
    $LocationChanged = $true
    Write-Log "STEP9 MORNING V2 START RUN_ID=$RunId DATE=$Date ROLE=$InvocationRole"

    if ($null -eq $StockholmZone) {
        throw "Windows time zone 'W. Europe Standard Time' is unavailable."
    }
    $SessionDate = [datetime]::ParseExact(
        $Date,
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None
    )
    $StockholmNow = Get-StockholmNow
    if ($StockholmNow.ToString("yyyy-MM-dd") -ne $Date) {
        throw "Live Morning V2 may only run for today's Stockholm date. Stockholm now is $($StockholmNow.ToString('o'))."
    }

    $LaunchEarliest = New-StockholmMoment -SessionDate $Date -Clock "09:43:30"
    $LaunchLatest = New-StockholmMoment -SessionDate $Date -Clock "09:45:35"
    $CollectorStart = New-StockholmMoment -SessionDate $Date -Clock "09:45:02"
    $CollectorRetryLatestStart = New-StockholmMoment -SessionDate $Date -Clock "09:46:25"
    $Step9TDecisionTime = New-StockholmMoment -SessionDate $Date -Clock "09:48:00"
    $Step9SLatestStart = New-StockholmMoment -SessionDate $Date -Clock "09:49:25"
    $Step9TLatestStart = New-StockholmMoment -SessionDate $Date -Clock "09:49:25"
    $Step9ULatestStart = New-StockholmMoment -SessionDate $Date -Clock "09:49:50"

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Project Python is missing: $Python"
    }
    if (-not (Test-Path -LiteralPath $Support -PathType Leaf)) {
        throw "Morning V2 support tool is missing: $Support"
    }
    $SupportUsable = $true
    if (-not (Test-Path -LiteralPath $RuntimeManifest -PathType Leaf)) {
        throw "Morning V2 runtime manifest is missing: $RuntimeManifest"
    }

    Invoke-PythonLogged -Label "VERIFY MORNING V2 RUNTIME MANIFEST" -TimeoutSeconds 60 -Arguments @(
        $Support,
        "runtime-manifest",
        "--manifest",
        $RuntimeManifest,
        "--root",
        $Root,
        "--json-out",
        $RuntimeCheckJson
    ) | Out-Null
    $RuntimeManifestResult = Get-Content -LiteralPath $RuntimeCheckJson -Raw | ConvertFrom-Json
    if ([string](Get-ObjectField -InputObject $RuntimeManifestResult -Name "status" -Default "") -ne "STEP9_MORNING_V2_RUNTIME_COMPATIBILITY_PASSED") {
        throw "Morning V2 runtime manifest verification did not report PASSED."
    }
    $RuntimeValidated = $true

    $MutexName = "STEP9_FULL_MORNING_V2_$($Date.Replace('-', ''))"
    $Mutex = New-Object Threading.Mutex($false, $MutexName)
    $WaitMilliseconds = if ($InvocationRole -eq "WATCHDOG") { $WatchdogMutexWaitSeconds * 1000 } else { 0 }
    $MutexWaitStarted = [DateTimeOffset]::UtcNow
    try {
        $MutexOwned = $Mutex.WaitOne($WaitMilliseconds)
    }
    catch [Threading.AbandonedMutexException] {
        $MutexOwned = $true
        $MutexAbandoned = $true
        $MutexState = "ABANDONED_MUTEX_RECOVERED"
    }
    $MutexWaitSeconds = ([DateTimeOffset]::UtcNow - $MutexWaitStarted).TotalSeconds
    if (-not $MutexOwned) {
        $MutexState = "OWNER_ACTIVE_TIMEOUT"
        $SuppressFallback = $true
        $SuppressFallbackReason = "ANOTHER_LIVE_OWNER_REMAINS_ACTIVE"
        throw "Another Step 9 Morning V2 process still owns today's session mutex."
    }
    if (-not $MutexAbandoned) {
        $MutexState = "ACQUIRED"
        if ($InvocationRole -eq "WATCHDOG" -and $MutexWaitSeconds -ge 1.0) {
            $WatchdogObservedPriorOwner = $true
            $MutexState = "WATCHDOG_ACQUIRED_AFTER_PRIOR_OWNER_RELEASE"
        }
    }

    Stop-OrphanedProcessesAfterAbandonment

    if (-not ([System.Management.Automation.PSTypeName]'Step9MorningV2Power').Type) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Step9MorningV2Power {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
    }
    try {
        [Step9MorningV2Power]::SetThreadExecutionState([Convert]::ToUInt32("80000003", 16)) | Out-Null
        $PowerStateEnabled = $true
    }
    catch {
        Write-Log "WARNING: SLEEP PREVENTION COULD NOT BE ENABLED: $($_.Exception.Message)"
    }

    $Initial = Get-LiveStatus
    $LiveStatus = $Initial
    if ([bool](Get-ObjectField -InputObject $Initial -Name "live_complete" -Default $false)) {
        Write-Log "LIVE CHAIN REPORTS COMPLETE; RUNNING CANONICAL VERIFICATION WITHOUT RERUN"
        $LiveStatus = Verify-AllLiveStages
        $LiveAccepted = $true
    }
    else {
        if ($WatchdogObservedPriorOwner -and -not $MutexAbandoned) {
            $SuppressFallback = $true
            $SuppressFallbackReason = "PRIOR_OWNER_COMPLETED_ITS_OWN_FALLBACK_LIFECYCLE"
            throw "The prior Morning V2 owner released normally without a complete live chain; its immutable registry is authoritative."
        }

        $Now = Get-StockholmNow
        if ($Now -lt $LaunchEarliest) {
            Write-Log "MORNING V2 STARTED EARLY; WAITING FOR THE FROZEN COLLECTION POINT"
        }
        if ($Now -gt $LaunchLatest) {
            throw "Morning V2 live start deadline 09:45:35 Stockholm time passed. No live engine will be reconstructed in place."
        }

        $SnapshotsExist = (
            (Test-Path -LiteralPath $Snapshot0940 -PathType Leaf) -and
            (Test-Path -LiteralPath "$Snapshot0940.manifest.json" -PathType Leaf) -and
            (Test-Path -LiteralPath $Snapshot0945 -PathType Leaf) -and
            (Test-Path -LiteralPath "$Snapshot0945.manifest.json" -PathType Leaf)
        )

        if (-not $SnapshotsExist) {
            Wait-UntilStockholm -Target $CollectorStart
            [void](Ensure-CollectorReadiness)
        }
        else {
            Write-Log "BOTH IMMUTABLE SNAPSHOTS ALREADY EXIST; VERIFYING WITHOUT RECOLLECTION"
        }

        New-Item -ItemType Directory -Path $SnapshotDir -Force | Out-Null
        $Snapshot0940Json = Join-Path $Logs "step9_morning_v2_snapshot_0940_${RunId}.json"
        $Snapshot0945Json = Join-Path $Logs "step9_morning_v2_snapshot_0945_${RunId}.json"
        $SnapshotResults["09:40"] = Ensure-ImmutableSnapshot -Cutoff "09:40" -Destination $Snapshot0940 -ResultJson $Snapshot0940Json
        $SnapshotResults["09:45"] = Ensure-ImmutableSnapshot -Cutoff "09:45" -Destination $Snapshot0945 -ResultJson $Snapshot0945Json

        $AfterSnapshots = Get-LiveStatus
        $IJob = $null
        $LJob = $null
        $SJob = $null
        $RJob = $null
        $TJob = $null
        $UJob = $null

        $IState = Get-ObjectField -InputObject $AfterSnapshots -Name "step9i"
        if (-not [bool](Get-ObjectField -InputObject $IState -Name "sealed" -Default $false)) {
            $IJob = Start-StageProcess -Stage "step9i" -Arguments @(
                "--date", $Date,
                "--source-db", $Snapshot0940Rel,
                "--ledger-db", "data\step9i_v2_shadow_ledger.db"
            )
        }
        else {
            [void](Verify-LiveStage -Stage "step9i")
        }

        $LState = Get-ObjectField -InputObject $AfterSnapshots -Name "step9l"
        if (-not [bool](Get-ObjectField -InputObject $LState -Name "sealed" -Default $false)) {
            $LJob = Start-StageProcess -Stage "step9l" -Arguments @(
                "--date", $Date,
                "--source-db", $Snapshot0940Rel,
                "--ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db"
            )
        }
        else {
            [void](Verify-LiveStage -Stage "step9l")
        }

        $LPassed = $true
        if ($null -ne $LJob) {
            $LPassed = Finish-StageProcess -Job $LJob
        }

        if ($LPassed) {
            $StateAfterL = Get-LiveStatus
            $SState = Get-ObjectField -InputObject $StateAfterL -Name "step9s"
            if (-not [bool](Get-ObjectField -InputObject $SState -Name "sealed" -Default $false)) {
                if ((Get-StockholmNow) -le $Step9SLatestStart) {
                    $SJob = Start-StageProcess -Stage "step9s" -Arguments @(
                        "--date", $Date,
                        "--source-db", $Snapshot0940Rel,
                        "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
                        "--ledger-db", "data\step9s_prospective_contingency_shadow_v1.db"
                    )
                }
                else {
                    $StageFailures["step9s"] = "LIVE_START_DEADLINE_PASSED"
                }
            }
            else {
                [void](Verify-LiveStage -Stage "step9s")
            }

            $RState = Get-ObjectField -InputObject $StateAfterL -Name "step9r"
            if (-not [bool](Get-ObjectField -InputObject $RState -Name "sealed" -Default $false)) {
                $RJob = Start-StageProcess -Stage "step9r" -Arguments @(
                    "--date", $Date,
                    "--source-db", $Snapshot0940Rel,
                    "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
                    "--research-db", "data\step9r_candidate_ranking_research_v1.db",
                    "--ledger-db", "data\step9r_prospective_selector_shadow_v1.db"
                )
            }
            else {
                [void](Verify-LiveStage -Stage "step9r")
            }

            Wait-UntilStockholm -Target $Step9TDecisionTime
            $StateBeforeT = Get-LiveStatus
            $TState = Get-ObjectField -InputObject $StateBeforeT -Name "step9t"
            $TPassed = [bool](Get-ObjectField -InputObject $TState -Name "sealed" -Default $false)
            if (-not $TPassed) {
                if ((Get-StockholmNow) -le $Step9TLatestStart) {
                    $TJob = Start-StageProcess -Stage "step9t" -Arguments @(
                        "--date", $Date,
                        "--source-db", $Snapshot0945Rel,
                        "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
                        "--ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db"
                    )
                    $TPassed = Finish-StageProcess -Job $TJob
                }
                else {
                    $StageFailures["step9t"] = "LIVE_START_DEADLINE_PASSED"
                }
            }
            else {
                [void](Verify-LiveStage -Stage "step9t")
            }

            $UPassed = $false
            if ($TPassed) {
                $StateAfterT = Get-LiveStatus
                $UState = Get-ObjectField -InputObject $StateAfterT -Name "step9u"
                $UPassed = [bool](Get-ObjectField -InputObject $UState -Name "sealed" -Default $false)
                if (-not $UPassed) {
                    if ((Get-StockholmNow) -le $Step9ULatestStart) {
                        $UJob = Start-StageProcess -Stage "step9u" -Arguments @(
                            "--date", $Date,
                            "--step9t-ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db",
                            "--ledger-db", "data\step9u_contingency_selector_prospective_shadow_v1.db"
                        )
                        $UPassed = Finish-StageProcess -Job $UJob
                    }
                    else {
                        $StageFailures["step9u"] = "LIVE_START_DEADLINE_PASSED"
                    }
                }
                else {
                    [void](Verify-LiveStage -Stage "step9u")
                }
            }

            if ($null -ne $SJob) {
                [void](Finish-StageProcess -Job $SJob)
            }
            if ($null -ne $RJob) {
                [void](Finish-StageProcess -Job $RJob)
            }
        }
        else {
            $StageFailures["downstream"] = "STEP9L_NOT_VERIFIED"
        }

        if ($null -ne $IJob) {
            [void](Finish-StageProcess -Job $IJob)
        }

        $LiveStatus = Get-LiveStatus
        if (-not [bool](Get-ObjectField -InputObject $LiveStatus -Name "live_complete" -Default $false)) {
            throw "The live morning chain remained incomplete after all eligible stages finished."
        }
        $LiveStatus = Verify-AllLiveStages
        $LiveAccepted = $true

        Invoke-PythonLogged -Label "DEFERRED MORNING EXPORTS" -TimeoutSeconds 240 -NonCritical -Arguments @(
            "-m", $StageModule, "export-all",
            "--date", $Date,
            "--step9i-ledger-db", "data\step9i_v2_shadow_ledger.db",
            "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
            "--step9s-ledger-db", "data\step9s_prospective_contingency_shadow_v1.db",
            "--step9t-ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db",
            "--step9u-ledger-db", "data\step9u_contingency_selector_prospective_shadow_v1.db"
        ) | Out-Null
        Invoke-PythonLogged -Label "STEP 9Q READ-ONLY REPORT" -TimeoutSeconds 240 -NonCritical -Arguments @(
            "-m",
            "RegimeTrading.scripts.step9q_powerbi_excel_feed",
            "--date",
            $Date,
            "--require-both-engines"
        ) | Out-Null
    }
}
catch {
    Add-FatalError -Message $_.Exception.Message
    try {
        Write-Log "LIVE ERROR: $($_.Exception.Message)"
    }
    catch {
        Write-Warning "Could not append the live error to the Morning V2 log."
    }
}
finally {
    try {
        Stop-AndDrainAllStageProcesses
    }
    catch {
        $FallbackSafe = $false
        Add-FatalError -Message "STAGE_CLEANUP_ERROR: $($_.Exception.Message)"
    }

    if ($SupportUsable -and $RuntimeValidated -and $MutexOwned -and -not $LiveAccepted) {
        try {
            $Observed = Get-LiveStatus
            $LiveStatus = $Observed
            if ([bool](Get-ObjectField -InputObject $Observed -Name "live_complete" -Default $false)) {
                $LiveStatus = Verify-AllLiveStages
                $LiveAccepted = $true
                Write-Log "LIVE CHAIN COMPLETED DURING CLEANUP AND PASSED CANONICAL VERIFICATION"
            }
        }
        catch {
            Add-FatalError -Message "FINAL_STATUS_ERROR: $($_.Exception.Message)"
        }
    }

    if ($null -eq $LiveStatus) {
        $LiveStatus = New-FailureStatus
    }

    $ShouldFallback = (
        -not $LiveAccepted -and
        -not $NoMockFallback.IsPresent -and
        $RuntimeValidated -and
        $MutexOwned -and
        $FallbackSafe -and
        -not $SuppressFallback
    )

    if ($ShouldFallback) {
        try {
            Assert-NoLiveStageProcessBeforeFallback
            if (-not (Test-Path -LiteralPath $Fallback -PathType Leaf)) {
                throw "Mock fallback runner is missing: $Fallback"
            }
            $FallbackJson = Join-Path $Logs "step9_morning_v2_fallback_${RunId}.json"
            if (Test-Path -LiteralPath $FallbackJson) {
                throw "Per-run mock fallback result already exists: $FallbackJson"
            }
            Write-Log "START ISOLATED MOCK FALLBACK"
            & $Fallback `
                -Date $Date `
                -ProjectRoot $Root `
                -Snapshot0940 $Snapshot0940 `
                -Snapshot0945 $Snapshot0945 `
                -MockBaseRoot $MockBaseRoot `
                -ResultJson $FallbackJson

            if (-not (Test-Path -LiteralPath $FallbackJson -PathType Leaf)) {
                throw "Mock fallback returned without an immutable result JSON."
            }
            $FallbackResult = Get-Content -LiteralPath $FallbackJson -Raw | ConvertFrom-Json
            if ([string](Get-ObjectField -InputObject $FallbackResult -Name "status" -Default "") -ne "MOCK_FALLBACK_COMPLETE") {
                throw "Mock fallback result did not report MOCK_FALLBACK_COMPLETE."
            }
            Write-Log "END ISOLATED MOCK FALLBACK STATUS=MOCK_FALLBACK_COMPLETE"
        }
        catch {
            $FallbackResult = [PSCustomObject]@{
                status = "MOCK_FALLBACK_FAILED"
                error = $_.Exception.Message
            }
            Add-FatalError -Message "MOCK_FALLBACK_ERROR: $($_.Exception.Message)"
            try {
                Write-Log "MOCK FALLBACK ERROR: $($_.Exception.Message)"
            }
            catch {}
        }
    }
    elseif (-not $LiveAccepted -and -not $NoMockFallback.IsPresent) {
        if ([string]::IsNullOrWhiteSpace($SuppressFallbackReason)) {
            if (-not $RuntimeValidated) {
                $SuppressFallbackReason = "RUNTIME_MANIFEST_NOT_VALIDATED"
            }
            elseif (-not $MutexOwned) {
                $SuppressFallbackReason = "SESSION_MUTEX_NOT_OWNED"
            }
            elseif (-not $FallbackSafe) {
                $SuppressFallbackReason = "LIVE_PROCESS_SAFETY_NOT_PROVEN"
            }
            else {
                $SuppressFallbackReason = "FALLBACK_NOT_SAFE"
            }
        }
        $SuppressFallback = $true
        $FallbackResult = [PSCustomObject]@{
            status = "MOCK_FALLBACK_SUPPRESSED"
            reason = $SuppressFallbackReason
        }
    }

    try {
        Write-ImmutableRegistry
    }
    catch {
        Add-FatalError -Message "REGISTRY_WRITE_ERROR: $($_.Exception.Message)"
        Write-Warning "Could not write the immutable Morning V2 registry: $($_.Exception.Message)"
    }

    if ($PowerStateEnabled) {
        try {
            [Step9MorningV2Power]::SetThreadExecutionState([Convert]::ToUInt32("80000000", 16)) | Out-Null
        }
        catch {}
    }
    if ($MutexOwned -and $null -ne $Mutex) {
        try {
            $Mutex.ReleaseMutex()
        }
        catch {}
    }
    if ($null -ne $Mutex) {
        $Mutex.Dispose()
    }
    if ($LocationChanged) {
        Set-Location -LiteralPath $PreviousLocation
    }
}

$EffectiveClassification = Get-EffectiveClassification
$SealedCount = [int](Get-ObjectField -InputObject $LiveStatus -Name "sealed_count" -Default 0)

Write-Host ""
Write-Host "STEP9_FULL_LIVE_MORNING_ORCHESTRATOR_V2"
Write-Host "RUN ID: $RunId"
Write-Host "DATE: $Date"
Write-Host "LIVE CLASSIFICATION: $EffectiveClassification"
Write-Host "LIVE SEALED STAGES: $SealedCount / 6"
Write-Host "CANONICAL LIVE VERIFICATION: $LiveAccepted"
if ($null -ne $FallbackResult) {
    Write-Host "MOCK FALLBACK STATUS: $(Get-ObjectField -InputObject $FallbackResult -Name 'status' -Default 'UNKNOWN')"
}
if ($RegistryWritten) {
    Write-Host "IMMUTABLE REGISTRY: $RegistryPath"
}
else {
    Write-Host "IMMUTABLE REGISTRY: WRITE FAILED"
}
Write-Host "MASTER LOG: $Log"
Write-Host "STEP 9S MANDATORY BENCHMARK CONTROL: TRUE WHEN SEALED"
Write-Host "STEP 9U MANDATORY CONTROL: FALSE"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"

if (-not $RegistryWritten) {
    throw "The live result could not be sealed into an immutable per-run registry."
}
if (-not $LiveAccepted) {
    throw "Live Step 9 Morning V2 did not complete canonical verification. Any isolated mock result is preserved separately."
}
