param(
    [string]$Date = "",
    [string]$ProjectRoot = "",
    [switch]$ReplaceExisting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = $PSScriptRoot
}

function Get-NormalizedFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd("\")
}

function Get-StockholmTimeZone {
    foreach ($Id in @("W. Europe Standard Time", "Europe/Stockholm")) {
        try {
            return [System.TimeZoneInfo]::FindSystemTimeZoneById($Id)
        }
        catch {
            continue
        }
    }
    throw "The Stockholm time zone is not available on this computer."
}

function New-StockholmInstant {
    param(
        [Parameter(Mandatory = $true)][string]$SessionDate,
        [Parameter(Mandatory = $true)][string]$Clock,
        [Parameter(Mandatory = $true)][System.TimeZoneInfo]$TimeZone
    )
    $Local = [datetime]::ParseExact(
        "$SessionDate $Clock",
        "yyyy-MM-dd HH:mm:ss",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None
    )
    $Local = [datetime]::SpecifyKind($Local, [DateTimeKind]::Unspecified)
    if ($TimeZone.IsInvalidTime($Local)) {
        throw "The requested Stockholm task time is invalid: $SessionDate $Clock"
    }
    if ($TimeZone.IsAmbiguousTime($Local)) {
        throw "The requested Stockholm task time is ambiguous: $SessionDate $Clock"
    }
    return New-Object DateTimeOffset($Local, $TimeZone.GetUtcOffset($Local))
}

function New-Step9Action {
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][string]$RunnerPath,
        [Parameter(Mandatory = $true)][string]$SessionDate,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    foreach ($Value in @($RunnerPath, $SessionDate, $Role)) {
        if ($Value.Contains('"')) {
            throw "A scheduled-task argument contains an unsupported quote character."
        }
    }
    $PowerShellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $PowerShellExe -PathType Leaf)) {
        throw "Windows PowerShell executable not found: $PowerShellExe"
    }
    $Arguments = (
        '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass ' +
        '-WindowStyle Hidden ' +
        "-File `"$RunnerPath`" " +
        "-Date `"$SessionDate`" " +
        "-InvocationRole `"$Role`""
    )
    return New-ScheduledTaskAction `
        -Execute $PowerShellExe `
        -Argument $Arguments `
        -WorkingDirectory $WorkingDirectory
}

$StockholmZone = Get-StockholmTimeZone
$StockholmNow = [TimeZoneInfo]::ConvertTime(
    [DateTimeOffset]::UtcNow,
    $StockholmZone
)
if (-not $Date) {
    $Date = $StockholmNow.Date.AddDays(1).ToString("yyyy-MM-dd")
}
try {
    $SessionDate = [datetime]::ParseExact(
        $Date,
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture
    )
}
catch {
    throw "Date must use YYYY-MM-DD format."
}

$ProjectRoot = Get-NormalizedFullPath -Path $ProjectRoot
$Runner = Join-Path $ProjectRoot "run_step9_full_live_morning_v2.ps1"
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Morning V2 runner not found: $Runner"
}

$CompactDate = $Date.Replace("-", "")
$PrimaryName = "Step9_Morning_V2_Primary_$CompactDate"
$WatchdogName = "Step9_Morning_V2_Watchdog_$CompactDate"
$PrimaryStockholm = New-StockholmInstant `
    -SessionDate $Date `
    -Clock "09:39:00" `
    -TimeZone $StockholmZone
$WatchdogStockholm = New-StockholmInstant `
    -SessionDate $Date `
    -Clock "09:39:30" `
    -TimeZone $StockholmZone
$PrimaryAt = $PrimaryStockholm.ToLocalTime().LocalDateTime
$WatchdogAt = $WatchdogStockholm.ToLocalTime().LocalDateTime
if ((Get-Date) -ge $PrimaryAt) {
    throw (
        "Primary task time has already passed: Stockholm={0} machine_local={1}" -f
        $PrimaryStockholm.ToString("o"),
        $PrimaryAt.ToString("o")
    )
}
if ($SessionDate.DayOfWeek -in @(
    [DayOfWeek]::Saturday,
    [DayOfWeek]::Sunday
)) {
    throw "The requested session date is a weekend: $Date"
}

$RuntimeManifest = Join-Path $ProjectRoot (
    "config\step9_morning_v2_runtime_manifest.json"
)
if (-not (Test-Path -LiteralPath $RuntimeManifest -PathType Leaf)) {
    throw "Morning V2 runtime manifest is missing: $RuntimeManifest"
}
$RuntimeManifestHash = (
    Get-FileHash -LiteralPath $RuntimeManifest -Algorithm SHA256
).Hash.ToLower()
$LogRoot = Join-Path $ProjectRoot "logs"
$QualifiedPreflight = $null
if (Test-Path -LiteralPath $LogRoot -PathType Container) {
    foreach ($Candidate in @(
        Get-ChildItem -LiteralPath $LogRoot -File `
            -Filter "step9_full_tonight_preflight_v2_*.json" |
            Sort-Object LastWriteTimeUtc -Descending
    )) {
        try {
            $Payload = Get-Content -LiteralPath $Candidate.FullName -Raw |
                ConvertFrom-Json
            $Names = @($Payload.PSObject.Properties.Name)
            $HasRequiredFields = (
                $Names -contains "status" -and
                $Names -contains "qualified" -and
                $Names -contains "next_session_date" -and
                $Names -contains "runtime_manifest_sha256" -and
                $Names -contains "database_integrity_check_pending" -and
                $Names -contains "databases_and_sidecars_unchanged"
            )
            if (
                $HasRequiredFields -and
                [string]$Payload.status -eq
                    "STEP9_MORNING_V2_PREFLIGHT_QUALIFIED" -and
                [bool]$Payload.qualified -and
                [string]$Payload.next_session_date -eq $Date -and
                ([string]$Payload.runtime_manifest_sha256).ToLower() -eq
                    $RuntimeManifestHash -and
                -not [bool]$Payload.database_integrity_check_pending -and
                [bool]$Payload.databases_and_sidecars_unchanged
            ) {
                $QualifiedPreflight = [PSCustomObject]@{
                    path = $Candidate.FullName
                    sha256 = (
                        Get-FileHash -LiteralPath $Candidate.FullName `
                            -Algorithm SHA256
                    ).Hash.ToLower()
                }
                break
            }
        }
        catch {
            Write-Warning (
                "Ignoring unreadable preflight marker $($Candidate.Name): " +
                $_.Exception.Message
            )
        }
    }
}
if ($null -eq $QualifiedPreflight) {
    throw (
        "No fully qualified Morning V2 preflight marker matches session $Date " +
        "and the installed runtime manifest. Run tonight preflight first."
    )
}

$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($CurrentIdentity)) {
    throw "Could not resolve the current Windows identity."
}

$ConflictingV1 = @(
    Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object {
            $_.State -ne "Disabled" -and
            @($_.Actions | Where-Object {
                $ArgumentProperty = $_.PSObject.Properties["Arguments"]
                $ArgumentText = if ($null -eq $ArgumentProperty) {
                    ""
                }
                else {
                    [string]$ArgumentProperty.Value
            }

            $ArgumentText -match "run_step9_(full_live_morning|tu_live_morning)_v1\.ps1"
        }).Count -gt 0
        }
)
if ($ConflictingV1.Count -gt 0) {
    $Names = @($ConflictingV1 | ForEach-Object { $_.TaskName }) -join ", "
    throw (
        "Enabled V1 morning scheduled task(s) would race V2: $Names. " +
        "Inspect and disable them explicitly before registering V2."
    )
}

$ReceiptDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Path $ReceiptDir -Force | Out-Null
$RecoveryStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss_fff")
$RecoveryId = [Guid]::NewGuid().ToString("N")
$RecoveryDir = Join-Path $ReceiptDir (
    "step9_morning_v2_task_recovery_{0}_{1}_{2}" -f
    $CompactDate,
    $RecoveryStamp,
    $RecoveryId
)
$ExistingXml = [ordered]@{}
$ExistingRecoveryFiles = [ordered]@{}
foreach ($Name in @($PrimaryName, $WatchdogName)) {
    $Existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($null -ne $Existing -and -not $ReplaceExisting) {
        throw (
            "Scheduled task already exists: $Name. " +
            "Rerun with -ReplaceExisting only after inspection."
        )
    }
    if ($null -ne $Existing) {
        $Xml = Export-ScheduledTask -TaskName $Name
        if (-not (Test-Path -LiteralPath $RecoveryDir -PathType Container)) {
            New-Item -ItemType Directory -Path $RecoveryDir -Force | Out-Null
        }
        $SafeName = $Name -replace "[^A-Za-z0-9_.-]", "_"
        $RecoveryPath = Join-Path $RecoveryDir "${SafeName}.xml"
        if (Test-Path -LiteralPath $RecoveryPath) {
            throw "Unique scheduled-task recovery file unexpectedly exists: $RecoveryPath"
        }
        $Xml | Set-Content -LiteralPath $RecoveryPath -Encoding Unicode
        if (-not (Test-Path -LiteralPath $RecoveryPath -PathType Leaf)) {
            throw "Could not persist scheduled-task recovery XML: $RecoveryPath"
        }
        $ExistingXml[$Name] = $Xml
        $ExistingRecoveryFiles[$Name] = [ordered]@{
            path = $RecoveryPath
            sha256 = (
                Get-FileHash -LiteralPath $RecoveryPath -Algorithm SHA256
            ).Hash.ToLower()
        }
    }
}

$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentIdentity `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

$PrimaryAction = New-Step9Action `
    -Role "PRIMARY" `
    -RunnerPath $Runner `
    -SessionDate $Date `
    -WorkingDirectory $ProjectRoot
$WatchdogAction = New-Step9Action `
    -Role "WATCHDOG" `
    -RunnerPath $Runner `
    -SessionDate $Date `
    -WorkingDirectory $ProjectRoot

$PrimaryTask = New-ScheduledTask `
    -Action $PrimaryAction `
    -Trigger (New-ScheduledTaskTrigger -Once -At $PrimaryAt) `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Step 9 Morning V2 primary prospective chain with isolated mock fallback."

$WatchdogTask = New-ScheduledTask `
    -Action $WatchdogAction `
    -Trigger (New-ScheduledTaskTrigger -Once -At $WatchdogAt) `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Step 9 Morning V2 watchdog. It waits behind the primary mutex and recovers an abandoned run."

$ReceiptStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss_fff")
$ReceiptId = [Guid]::NewGuid().ToString("N")
$ReceiptPath = Join-Path $ReceiptDir (
    "step9_morning_v2_tasks_{0}_{1}_{2}.json" -f
    $CompactDate,
    $ReceiptStamp,
    $ReceiptId
)
$ReceiptTemp = "$ReceiptPath.tmp"
if ((Test-Path -LiteralPath $ReceiptPath) -or (Test-Path -LiteralPath $ReceiptTemp)) {
    throw "Unique task-registration receipt path unexpectedly exists: $ReceiptPath"
}

$RegisteredThisRun = New-Object System.Collections.Generic.List[string]
try {
    foreach ($Name in $ExistingXml.Keys) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }

    Register-ScheduledTask -TaskName $PrimaryName -InputObject $PrimaryTask | Out-Null
    $RegisteredThisRun.Add($PrimaryName)
    Register-ScheduledTask -TaskName $WatchdogName -InputObject $WatchdogTask | Out-Null
    $RegisteredThisRun.Add($WatchdogName)

    $Primary = Get-ScheduledTask -TaskName $PrimaryName
    $Watchdog = Get-ScheduledTask -TaskName $WatchdogName
    $PrimaryInfo = Get-ScheduledTaskInfo -TaskName $PrimaryName
    $WatchdogInfo = Get-ScheduledTaskInfo -TaskName $WatchdogName

    if ($Primary.State -ne "Ready" -or $Watchdog.State -ne "Ready") {
        throw (
            "One or both Morning V2 tasks are not Ready. " +
            "Primary=$($Primary.State) Watchdog=$($Watchdog.State)"
        )
    }
    if ($PrimaryInfo.NextRunTime -ne $PrimaryAt) {
        throw "Primary task NextRunTime mismatch: $($PrimaryInfo.NextRunTime)"
    }
    if ($WatchdogInfo.NextRunTime -ne $WatchdogAt) {
        throw "Watchdog task NextRunTime mismatch: $($WatchdogInfo.NextRunTime)"
    }
    if ((Get-NormalizedFullPath $Primary.Actions[0].WorkingDirectory) -ne $ProjectRoot) {
        throw "Primary task working directory is incorrect."
    }
    if ((Get-NormalizedFullPath $Watchdog.Actions[0].WorkingDirectory) -ne $ProjectRoot) {
        throw "Watchdog task working directory is incorrect."
    }
    if (
        ([string]$Primary.Actions[0].Arguments) -notmatch '-InvocationRole "PRIMARY"' -or
        ([string]$Watchdog.Actions[0].Arguments) -notmatch '-InvocationRole "WATCHDOG"'
    ) {
        throw "Scheduled-task invocation role verification failed."
    }

    [ordered]@{
        status = "STEP9_MORNING_V2_TASKS_REGISTERED"
        registration_id = $ReceiptId
        session_date = $Date
        registered_at = (Get-Date).ToString("o")
        windows_identity = $CurrentIdentity
        qualified_preflight = [ordered]@{
            path = [string]$QualifiedPreflight.path
            sha256 = [string]$QualifiedPreflight.sha256
            runtime_manifest_sha256 = $RuntimeManifestHash
        }
        primary = [ordered]@{
            name = $PrimaryName
            stockholm_target = $PrimaryStockholm.ToString("o")
            machine_local_target = $PrimaryAt.ToString("o")
            next_run_time = $PrimaryInfo.NextRunTime.ToString("o")
            state = [string]$Primary.State
            arguments = [string]$Primary.Actions[0].Arguments
        }
        watchdog = [ordered]@{
            name = $WatchdogName
            stockholm_target = $WatchdogStockholm.ToString("o")
            machine_local_target = $WatchdogAt.ToString("o")
            next_run_time = $WatchdogInfo.NextRunTime.ToString("o")
            state = [string]$Watchdog.State
            arguments = [string]$Watchdog.Actions[0].Arguments
        }
        replaced_task_recovery_xml = $ExistingRecoveryFiles
        router_active = $false
        orders_enabled = $false
    } | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $ReceiptTemp -Encoding UTF8
    [IO.File]::Move($ReceiptTemp, $ReceiptPath)
}
catch {
    $RegistrationError = $_
    if (Test-Path -LiteralPath $ReceiptTemp -PathType Leaf) {
        Remove-Item -LiteralPath $ReceiptTemp -Force -ErrorAction SilentlyContinue
    }
    foreach ($Name in @($RegisteredThisRun)) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    }
    $RestoreFailures = New-Object System.Collections.Generic.List[string]
    foreach ($Name in $ExistingXml.Keys) {
        try {
            Register-ScheduledTask -TaskName $Name -Xml $ExistingXml[$Name] | Out-Null
            if ($null -eq (Get-ScheduledTask -TaskName $Name -ErrorAction Stop)) {
                throw "Restored task could not be read back."
            }
        }
        catch {
            $RestoreFailures.Add(
                "Could not restore previous scheduled task ${Name}: $($_.Exception.Message)"
            )
        }
    }
    if ($RestoreFailures.Count -gt 0) {
        $RecoveryPaths = @(
            $ExistingRecoveryFiles.Values |
                ForEach-Object { [string]$_.path }
        ) -join ", "
        throw (
            (
                "Scheduled-task registration failed: {0} Rollback also failed: {1} " +
                "Recovery XML copies: {2}"
            ) -f
            $RegistrationError.Exception.Message,
            ($RestoreFailures -join " | "),
            $RecoveryPaths
        )
    }
    throw $RegistrationError
}

Write-Host ""
Write-Host "STEP9 MORNING V2 TASKS: REGISTERED"
Write-Host (
    "PRIMARY  : {0} / Stockholm {1} / local {2} / {3}" -f
    $PrimaryName,
    $PrimaryStockholm.ToString("o"),
    $PrimaryInfo.NextRunTime.ToString("o"),
    $Primary.State
)
Write-Host (
    "WATCHDOG : {0} / Stockholm {1} / local {2} / {3}" -f
    $WatchdogName,
    $WatchdogStockholm.ToString("o"),
    $WatchdogInfo.NextRunTime.ToString("o"),
    $Watchdog.State
)
Write-Host "RECEIPT  : $ReceiptPath"
Write-Host "LOGON TYPE: INTERACTIVE - remain signed in; locking the screen is allowed."
Write-Host "COMPUTER MUST REMAIN ON, AWAKE, AND CONNECTED TO THE INTERNET."
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WILL BE SENT"
