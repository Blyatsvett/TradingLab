param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^\d{4}-\d{2}-\d{2}$")]
    [string]$Date,
    [string]$ProjectRoot = "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading",
    [string]$Snapshot0940 = "",
    [string]$Snapshot0945 = "",
    [string]$MockBaseRoot = "",
    [string]$ResultJson = "",
    [ValidateRange(30, 3600)]
    [int]$ChildTimeoutSeconds = 900,
    [ValidateRange(1, 30)]
    [int]$MockCollectorMaxAttempts = 12,
    [ValidateRange(1, 120)]
    [int]$MockCollectorRetrySeconds = 30,
    [ValidateRange(1, 10)]
    [int]$MockCollectorDays = 2,
    [ValidateRange(30, 600)]
    [int]$MockCollectorTimeoutSeconds = 180,
    [ValidatePattern("^\d{2}:\d{2}:\d{2}$")]
    [string]$MockDataRecoveryLatestStart = "18:00:00"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd([char]92, [char]47)
}

function Test-PathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $FullPath = Get-FullPath -Path $Path
    $FullRoot = Get-FullPath -Path $Root
    if ($FullPath.Equals($FullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $FullPath.StartsWith(
        $FullRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )
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

function ConvertTo-StockholmTimestamp {
    param(
        [Parameter(Mandatory = $true)][datetime]$SessionDate,
        [Parameter(Mandatory = $true)][string]$Clock,
        [Parameter(Mandatory = $true)][System.TimeZoneInfo]$TimeZone
    )
    $Parts = $Clock.Split(":")
    if ($Parts.Count -ne 3) {
        throw "Clock must use HH:mm:ss format: $Clock"
    }
    $Local = [datetime]::new(
        $SessionDate.Year,
        $SessionDate.Month,
        $SessionDate.Day,
        [int]$Parts[0],
        [int]$Parts[1],
        [int]$Parts[2],
        [System.DateTimeKind]::Unspecified
    )
    if ($TimeZone.IsInvalidTime($Local)) {
        throw "The requested Stockholm timestamp is invalid: $Date $Clock"
    }
    $Offset = $TimeZone.GetUtcOffset($Local)
    return [datetimeoffset]::new($Local, $Offset).ToString("yyyy-MM-ddTHH:mm:sszzz")
}

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Value)
    if ($null -eq $Value) {
        $Value = ""
    }
    if (($Value.Length -gt 0) -and ($Value -notmatch '[\s"]')) {
        return $Value
    }
    $Builder = New-Object System.Text.StringBuilder
    [void]$Builder.Append([char]34)
    $SlashCount = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq [char]92) {
            $SlashCount++
            continue
        }
        if ($Character -eq [char]34) {
            if ($SlashCount -gt 0) {
                [void]$Builder.Append(([string][char]92) * (($SlashCount * 2) + 1))
            }
            else {
                [void]$Builder.Append([char]92)
            }
            [void]$Builder.Append([char]34)
            $SlashCount = 0
            continue
        }
        if ($SlashCount -gt 0) {
            [void]$Builder.Append(([string][char]92) * $SlashCount)
            $SlashCount = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($SlashCount -gt 0) {
        [void]$Builder.Append(([string][char]92) * ($SlashCount * 2))
    }
    [void]$Builder.Append([char]34)
    return $Builder.ToString()
}

$script:ActiveProcesses = @{}
$script:TerminationWaitMilliseconds = 10000

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$PythonPathRoot,
        [Parameter(Mandatory = $true)][string]$Label,
        [int]$TimeoutSeconds = 900,
        [switch]$NonCritical
    )
    Write-Host ""
    Write-Host "=== $Label ==="
    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $FilePath
    $StartInfo.Arguments = (($Arguments | ForEach-Object {
        ConvertTo-NativeArgument -Value ([string]$_)
    }) -join " ")
    $StartInfo.WorkingDirectory = $WorkingDirectory
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    $SavedPythonPath = [System.Environment]::GetEnvironmentVariable(
        "PYTHONPATH",
        [System.EnvironmentVariableTarget]::Process
    )
    $SavedNoUserSite = [System.Environment]::GetEnvironmentVariable(
        "PYTHONNOUSERSITE",
        [System.EnvironmentVariableTarget]::Process
    )
    $SavedNoByteCode = [System.Environment]::GetEnvironmentVariable(
        "PYTHONDONTWRITEBYTECODE",
        [System.EnvironmentVariableTarget]::Process
    )
    try {
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONPATH", $PythonPathRoot, [System.EnvironmentVariableTarget]::Process
        )
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONNOUSERSITE", "1", [System.EnvironmentVariableTarget]::Process
        )
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONDONTWRITEBYTECODE", "1", [System.EnvironmentVariableTarget]::Process
        )
        $Started = $Process.Start()
    }
    finally {
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONPATH", $SavedPythonPath, [System.EnvironmentVariableTarget]::Process
        )
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONNOUSERSITE", $SavedNoUserSite, [System.EnvironmentVariableTarget]::Process
        )
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONDONTWRITEBYTECODE", $SavedNoByteCode, [System.EnvironmentVariableTarget]::Process
        )
    }
    if (-not $Started) {
        throw "Could not start $Label."
    }
    $script:ActiveProcesses[[string]$Process.Id] = $Process
    $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
    $StdErrTask = $Process.StandardError.ReadToEndAsync()
    $Completed = $Process.WaitForExit($TimeoutSeconds * 1000)
    if (-not $Completed) {
        $TerminationError = $null
        try {
            if (-not $Process.HasExited) {
                $Process.Kill()
            }
            if (-not $Process.WaitForExit($script:TerminationWaitMilliseconds)) {
                throw (
                    "$Label process $($Process.Id) did not exit within " +
                    "$($script:TerminationWaitMilliseconds) ms after Kill()."
                )
            }
        }
        catch {
            $TerminationError = $_
        }
        if ($null -eq $TerminationError) {
            $script:ActiveProcesses.Remove([string]$Process.Id)
            try { $Process.Dispose() } catch { }
        }
        else {
            throw (
                "$Label exceeded its $TimeoutSeconds second timeout and " +
                "termination could not be proven: " +
                $TerminationError.Exception.Message
            )
        }
        if ($NonCritical) {
            Write-Warning "$Label exceeded its $TimeoutSeconds second timeout."
            return $false
        }
        throw "$Label exceeded its $TimeoutSeconds second timeout."
    }
    $StdOut = $StdOutTask.Result
    $StdErr = $StdErrTask.Result
    $ExitCode = $Process.ExitCode
    $script:ActiveProcesses.Remove([string]$Process.Id)
    $Process.Dispose()

    if (-not [string]::IsNullOrWhiteSpace($StdOut)) {
        Write-Host $StdOut.TrimEnd()
    }
    if (-not [string]::IsNullOrWhiteSpace($StdErr)) {
        Write-Host $StdErr.TrimEnd()
    }
    if ($ExitCode -ne 0) {
        if ($NonCritical) {
            Write-Warning "$Label failed with exit code $ExitCode."
            return $false
        }
        throw "$Label failed with exit code $ExitCode."
    }
    return $true
}

function Stop-TrackedProcesses {
    $Failures = New-Object System.Collections.Generic.List[string]
    foreach ($Entry in @($script:ActiveProcesses.GetEnumerator())) {
        $Process = $Entry.Value
        try {
            if (-not $Process.HasExited) {
                $Process.Kill()
            }
            if (-not $Process.WaitForExit($script:TerminationWaitMilliseconds)) {
                throw (
                    "Process $($Process.Id) did not exit within " +
                    "$($script:TerminationWaitMilliseconds) ms after cleanup Kill()."
                )
            }
        }
        catch {
            $Failures.Add($_.Exception.Message)
        }
        if ($Process.HasExited) {
            try { $Process.Dispose() } catch { }
        }
    }
    $script:ActiveProcesses = @{}
    if ($Failures.Count -gt 0) {
        throw "Tracked-process cleanup failed: $($Failures -join ' | ')"
    }
}

function Get-DatabaseState {
    param([Parameter(Mandatory = $true)][string]$Root)
    $State = [ordered]@{}
    $DataRoot = Join-Path $Root "data"
    if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
        return $State
    }
    $Files = @(Get-ChildItem -LiteralPath $DataRoot -Recurse -File |
        Where-Object {
            $_.Name -match '\.(?:db|sqlite|sqlite3)(?:-wal|-shm|-journal)?$'
        } |
        Sort-Object FullName)
    foreach ($File in $Files) {
        $Relative = $File.FullName.Substring($Root.Length).TrimStart([char]92, [char]47)
        $State[$Relative] = [ordered]@{
            length = [long]$File.Length
            sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLower()
        }
    }
    return $State
}

function Compare-DatabaseState {
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$After
    )
    $BeforeKeys = @($Before.Keys | Sort-Object)
    $AfterKeys = @($After.Keys | Sort-Object)
    if (($BeforeKeys -join "`n") -ne ($AfterKeys -join "`n")) {
        throw "The real project database or sidecar inventory changed during mock fallback."
    }
    foreach ($Key in $BeforeKeys) {
        if (($Before[$Key].sha256 -ne $After[$Key].sha256) -or
            ([long]$Before[$Key].length -ne [long]$After[$Key].length)) {
            throw "A real project database or sidecar changed during mock fallback: $Key"
        }
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Payload,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Depth = 16
    )
    $Parent = Split-Path -Parent $Path
    if ($Parent) {
        New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    }
    $Temp = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    $Payload | ConvertTo-Json -Depth $Depth |
        Set-Content -LiteralPath $Temp -Encoding UTF8
    Move-Item -LiteralPath $Temp -Destination $Path -Force
}

function Assert-MockStage {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $Node = $State.$Stage
    if (-not [bool]$Node.sealed) {
        throw "$Stage is not sealed."
    }
    switch ($Stage) {
        "step9i" {
            if (($Node.run_mode -ne "MORNING_DECISION_SEAL") -or
                ([int]$Node.decision_rows -ne 184) -or
                ([int]$Node.decision_rows_actual -ne 184) -or
                ([int]$Node.point_in_time_failures -ne 0) -or
                ([int]$Node.regime_point_in_time_pass -ne 1)) {
                throw "Step 9I sealed state failed its structural checks."
            }
        }
        "step9l" {
            if (($Node.run_mode -ne "MORNING_DECISION_SEAL") -or
                ([int]$Node.decision_rows -ne 184) -or
                ([int]$Node.decision_rows_actual -ne 184) -or
                ([int]$Node.point_in_time_failures -ne 0) -or
                ([int]$Node.regime_point_in_time_pass -ne 1)) {
                throw "Step 9L sealed state failed its structural checks."
            }
        }
        "step9s" {
            if (([int]$Node.coverage_plan_rows -ne 1) -or
                ([int]$Node.point_in_time_pass -ne 1) -or
                ([int]$Node.router_active -ne 0) -or
                ([int]$Node.order_sent -ne 0) -or
                ($Node.source_step9l_batch_id -ne $State.step9l.batch_id)) {
                throw "Step 9S sealed state failed its dependency or safety checks."
            }
        }
        "step9r" {
            if (([int]$Node.candidate_rows -ne [int]$Node.candidate_rows_actual) -or
                ([int]$Node.selected_rows -ne [int]$Node.selected_rows_actual) -or
                ([int]$Node.selected_rows -lt 0) -or
                ([int]$Node.selected_rows -gt 2)) {
                throw "Step 9R sealed state failed its row-count checks."
            }
        }
        "step9t" {
            if (([int]$Node.ticker_row_count -ne 29) -or
                ([int]$Node.point_in_time_pass -ne 1) -or
                ([int]$Node.router_active -ne 0) -or
                ([int]$Node.order_sent -ne 0) -or
                ($Node.source_step9l_batch_id -ne $State.step9l.batch_id)) {
                throw "Step 9T sealed state failed its dependency or safety checks."
            }
        }
        "step9u" {
            if (([int]$Node.selected_count -lt 0) -or
                ([int]$Node.selected_count -gt 2) -or
                ([int]$Node.mandatory_control_active -ne 0) -or
                ([int]$Node.point_in_time_pass -ne 1) -or
                ([int]$Node.router_active -ne 0) -or
                ([int]$Node.order_sent -ne 0) -or
                ($Node.source_step9t_batch_id -ne $State.step9t.batch_id)) {
                throw "Step 9U sealed state failed its dependency or safety checks."
            }
        }
        default {
            throw "Unknown stage requested for mock verification: $Stage"
        }
    }
}

$ParsedDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
    $Date,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]::None,
    [ref]$ParsedDate
)) {
    throw "Session date is invalid: $Date"
}

$ProjectRoot = Get-FullPath -Path $ProjectRoot
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project root not found: $ProjectRoot"
}
if (-not $MockBaseRoot) {
    $MockBaseRoot = Join-Path $env:USERPROFILE "S9M"
}
$MockBaseRoot = Get-FullPath -Path $MockBaseRoot
if ((Test-PathWithin -Path $MockBaseRoot -Root $ProjectRoot) -or
    (Test-PathWithin -Path $ProjectRoot -Root $MockBaseRoot)) {
    throw "Mock base and real project must be completely separate directory trees."
}
if (Test-Path -LiteralPath $MockBaseRoot) {
    $BaseItem = Get-Item -LiteralPath $MockBaseRoot -Force
    if (($BaseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Mock base must not be a junction or symbolic link: $MockBaseRoot"
    }
}
else {
    New-Item -ItemType Directory -Path $MockBaseRoot -Force | Out-Null
}
if (-not $ResultJson) {
    $ResultId = "{0}_{1}" -f (
        [datetimeoffset]::UtcNow.ToString("yyyyMMdd_HHmmss_fff")
    ), ([guid]::NewGuid().ToString("N"))
    $ResultJson = Join-Path $ProjectRoot (
        "logs\step9_morning_v2_mock_fallback_${ResultId}.json"
    )
}
$ResultJson = Get-FullPath -Path $ResultJson
$RealLogsRoot = Get-FullPath -Path (Join-Path $ProjectRoot "logs")
$ResultLeaf = [IO.Path]::GetFileName($ResultJson)
if (-not (Test-PathWithin -Path $ResultJson -Root $RealLogsRoot)) {
    throw "The fallback result file must be written inside the real logs directory."
}
if (
    $ResultLeaf -notmatch
        "^step9_morning_v2_(mock_)?fallback_[A-Za-z0-9_.-]+\.json$"
) {
    throw "The fallback result filename is outside the approved unique naming contract."
}
if (Test-Path -LiteralPath $ResultJson) {
    throw "The immutable fallback result target already exists: $ResultJson"
}

$RealPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RealSupport = Join-Path $ProjectRoot "tools\step9_morning_v2_support.py"
$RealPriceDb = Join-Path $ProjectRoot "data\step9i_shadow_intraday_prices.db"
foreach ($RequiredPath in @($RealPython, $RealSupport, $RealPriceDb)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required fallback dependency is missing: $RequiredPath"
    }
}

$TimeZone = Get-StockholmTimeZone
$AsOfI = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:45:20" -TimeZone $TimeZone
$AsOfS = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:46:10" -TimeZone $TimeZone
$AsOfT = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:48:00" -TimeZone $TimeZone
$AsOfU = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:48:10" -TimeZone $TimeZone

$BeforeState = Get-DatabaseState -Root $ProjectRoot
$PrimaryError = $null
$IntegrityError = $null
$CleanupError = $null
$MockRoot = ""
$ManifestPath = ""
$FinalState = $null
$ResultStatus = "MOCK_FALLBACK_FAILED"
$MockPriceRecoveryRequired = $false
$MockPriceRecoveryPassed = $false
$MockPriceRecoveryHistory = New-Object System.Collections.ArrayList
$MissingTrustedSourceSnapshots = @()
$PreviousLocation = Get-Location
$OldPythonPath = $env:PYTHONPATH
$OldNoUserSite = $env:PYTHONNOUSERSITE
$OldNoByteCode = $env:PYTHONDONTWRITEBYTECODE

try {
    $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Compact = $Date.Replace("-", "")
    $MockId = "MOCK_${Compact}_MORNING_V2_FALLBACK_${Stamp}_$([guid]::NewGuid().ToString('N').Substring(0,8))"
    $MockRoot = Join-Path $MockBaseRoot $MockId
    if (Test-Path -LiteralPath $MockRoot) {
        throw "Unique mock destination unexpectedly already exists: $MockRoot"
    }
    New-Item -ItemType Directory -Path $MockRoot | Out-Null

    $null = & robocopy `
        $ProjectRoot `
        $MockRoot `
        /E /COPY:DAT /DCOPY:T /R:1 /W:1 /XJ `
        /NFL /NDL /NJH /NJS /NP `
        /XD ".venv" ".git" "__pycache__" ".pytest_cache" "logs" `
        /XF "*.pyc" "*.pyo" `
            "*.db" "*.db-wal" "*.db-shm" "*.db-journal" `
            "*.sqlite" "*.sqlite-wal" "*.sqlite-shm" "*.sqlite-journal" `
            "*.sqlite3" "*.sqlite3-wal" "*.sqlite3-shm" "*.sqlite3-journal"
    $RoboCode = $LASTEXITCODE
    if ($RoboCode -gt 7) {
        throw "Mock clone failed with robocopy exit code $RoboCode."
    }

    $MockLogs = Join-Path $MockRoot "logs"
    New-Item -ItemType Directory -Path $MockLogs -Force | Out-Null
    $Python = $RealPython
    $Support = Join-Path $MockRoot "tools\step9_morning_v2_support.py"
    if (-not (Test-Path -LiteralPath $Support -PathType Leaf)) {
        throw "The support tool was not copied into the isolated mock."
    }

    $RealDatabases = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "data") -Recurse -File |
        Where-Object { $_.Name -match '\.(?:db|sqlite|sqlite3)$' } |
        Sort-Object FullName)
    foreach ($Database in $RealDatabases) {
        $Relative = $Database.FullName.Substring($ProjectRoot.Length).TrimStart([char]92, [char]47)
        if ($Relative -like "data\step9_morning_v2_snapshots\*") {
            continue
        }
        $Destination = Join-Path $MockRoot $Relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
        Invoke-NativeChecked `
            -FilePath $RealPython `
            -Arguments @(
                $RealSupport,
                "sqlite-backup",
                "--source-db", $Database.FullName,
                "--dest-db", $Destination
            ) `
            -WorkingDirectory $ProjectRoot `
            -PythonPathRoot $ProjectRoot `
            -Label "CONSISTENT MOCK BACKUP: $Relative" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    }

    $MockSnapshotDir = Join-Path $MockRoot "data\step9_morning_v2_snapshots\$Date"
    New-Item -ItemType Directory -Path $MockSnapshotDir -Force | Out-Null
    $MockSnapshot0940Abs = Join-Path $MockSnapshotDir "prices_through_0940.db"
    $MockSnapshot0945Abs = Join-Path $MockSnapshotDir "prices_through_0945.db"
    $MockPriceDb = Join-Path $MockRoot "data\step9i_shadow_intraday_prices.db"

    $DefaultSnapshotDir = Join-Path $ProjectRoot "data\step9_morning_v2_snapshots\$Date"
    if (-not $Snapshot0940) {
        $Snapshot0940 = Join-Path $DefaultSnapshotDir "prices_through_0940.db"
    }
    if (-not $Snapshot0945) {
        $Snapshot0945 = Join-Path $DefaultSnapshotDir "prices_through_0945.db"
    }
    $SnapshotSpecs = @(
        [pscustomobject]@{ Source = $Snapshot0940; Destination = $MockSnapshot0940Abs; Cutoff = "09:40" },
        [pscustomobject]@{ Source = $Snapshot0945; Destination = $MockSnapshot0945Abs; Cutoff = "09:45" }
    )
    $MissingTrustedSourceSnapshots = @(
        $SnapshotSpecs |
            Where-Object {
                (-not $_.Source) -or
                (-not (Test-Path -LiteralPath $_.Source -PathType Leaf)) -or
                (-not (Test-Path -LiteralPath "$($_.Source).manifest.json" -PathType Leaf))
            } |
            ForEach-Object { $_.Cutoff }
    )

    function Get-MockPriceReadiness {
        param([Parameter(Mandatory = $true)][string]$Label)
        $SafeLabel = ($Label -replace "[^A-Za-z0-9]+", "_").Trim("_")
        $ReadinessJson = Join-Path $MockLogs (
            "mock_price_readiness_{0}_{1}.json" -f
            $SafeLabel,
            ([guid]::NewGuid().ToString("N").Substring(0, 8))
        )
        Invoke-NativeChecked `
            -FilePath $RealPython `
            -Arguments @(
                $Support,
                "status",
                "--date", $Date,
                "--prices", $MockPriceDb,
                "--json-out", $ReadinessJson
            ) `
            -WorkingDirectory $MockRoot `
            -PythonPathRoot $MockRoot `
            -Label "READ MOCK PRICE READINESS $Label" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        $Readiness = Get-Content -LiteralPath $ReadinessJson -Raw |
            ConvertFrom-Json
        $Prices = $Readiness.prices
        $Passed = (
            ([string]$Prices.sqlite_integrity).ToLowerInvariant() -eq "ok" -and
            ([int]$Prices.today_tickers -eq 29) -and
            [bool]$Prices.ready_through_0945
        )
        return [pscustomobject]@{
            passed = [bool]$Passed
            prices = $Prices
            evidence_file = $ReadinessJson
        }
    }

    $InitialMockReadiness = Get-MockPriceReadiness -Label "INITIAL"
    $MockPriceRecoveryRequired = (
        $MissingTrustedSourceSnapshots.Count -gt 0 -and
        -not [bool]$InitialMockReadiness.passed
    )
    $MockPriceRecoveryPassed = (
        -not $MockPriceRecoveryRequired -or
        [bool]$InitialMockReadiness.passed
    )
    [void]$MockPriceRecoveryHistory.Add([pscustomobject]@{
        attempt = 0
        kind = "INITIAL_ISOLATED_COPY"
        completed_at_stockholm = [System.TimeZoneInfo]::ConvertTime(
            [datetimeoffset]::Now,
            $TimeZone
        ).ToString("o")
        collector_exit_success = $null
        ready = [bool]$InitialMockReadiness.passed
        today_tickers = [int]$InitialMockReadiness.prices.today_tickers
        exact_0940_tickers = [int]$InitialMockReadiness.prices.exact_0940_tickers
        exact_0945_tickers = [int]$InitialMockReadiness.prices.exact_0945_tickers
        max_datetime_today = [string]$InitialMockReadiness.prices.max_datetime_today
        evidence_file = [string]$InitialMockReadiness.evidence_file
    })

    if ($MockPriceRecoveryRequired) {
        $RecoveryDeadline = [datetimeoffset]::Parse(
            (ConvertTo-StockholmTimestamp `
                -SessionDate $ParsedDate `
                -Clock $MockDataRecoveryLatestStart `
                -TimeZone $TimeZone),
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        Write-Host ""
        Write-Host "=== BOUNDED MOCK-ONLY PRICE RECOVERY ==="
        Write-Host (
            (
                "Trusted source snapshots missing: {0}. " +
                "Only the isolated mock price database may be refreshed."
            ) -f
            ($MissingTrustedSourceSnapshots -join ", ")
        )

        for (
            $Attempt = 1;
            $Attempt -le $MockCollectorMaxAttempts;
            $Attempt++
        ) {
            $AttemptStarted = [System.TimeZoneInfo]::ConvertTime(
                [datetimeoffset]::Now,
                $TimeZone
            )
            if ($AttemptStarted -gt $RecoveryDeadline) {
                Write-Host "Mock recovery latest-start deadline has passed."
                break
            }

            $CollectorSucceeded = Invoke-NativeChecked `
                -FilePath $RealPython `
                -Arguments @(
                    "-m",
                    "RegimeTrading.scripts.collect_step9i_shadow_data",
                    "--days", ([string]$MockCollectorDays),
                    "--interval", "5m",
                    "--db", $MockPriceDb,
                    "--skip-bootstrap"
                ) `
                -WorkingDirectory $MockRoot `
                -PythonPathRoot $MockRoot `
                -Label "MOCK-ONLY PRICE COLLECTION ATTEMPT $Attempt" `
                -TimeoutSeconds $MockCollectorTimeoutSeconds `
                -NonCritical

            $AttemptReadiness = Get-MockPriceReadiness -Label "ATTEMPT_$Attempt"
            [void]$MockPriceRecoveryHistory.Add([pscustomobject]@{
                attempt = $Attempt
                kind = "MOCK_ONLY_COLLECTOR"
                completed_at_stockholm = [System.TimeZoneInfo]::ConvertTime(
                    [datetimeoffset]::Now,
                    $TimeZone
                ).ToString("o")
                collector_exit_success = [bool]$CollectorSucceeded
                ready = [bool]$AttemptReadiness.passed
                today_tickers = [int]$AttemptReadiness.prices.today_tickers
                exact_0940_tickers = [int]$AttemptReadiness.prices.exact_0940_tickers
                exact_0945_tickers = [int]$AttemptReadiness.prices.exact_0945_tickers
                max_datetime_today = [string]$AttemptReadiness.prices.max_datetime_today
                evidence_file = [string]$AttemptReadiness.evidence_file
            })

            if ([bool]$AttemptReadiness.passed) {
                $MockPriceRecoveryPassed = $true
                Write-Host "MOCK-ONLY PRICE RECOVERY: PASSED ON ATTEMPT $Attempt"
                break
            }

            $NowStockholm = [System.TimeZoneInfo]::ConvertTime(
                [datetimeoffset]::Now,
                $TimeZone
            )
            if (
                $Attempt -lt $MockCollectorMaxAttempts -and
                $NowStockholm.AddSeconds($MockCollectorRetrySeconds) -le
                    $RecoveryDeadline
            ) {
                Write-Host (
                    "Mock price readiness is still incomplete; retrying in " +
                    "$MockCollectorRetrySeconds seconds."
                )
                Start-Sleep -Seconds $MockCollectorRetrySeconds
            }
        }

        if (-not $MockPriceRecoveryPassed) {
            $LastRecovery = $MockPriceRecoveryHistory[
                $MockPriceRecoveryHistory.Count - 1
            ]
            throw (
                (
                    "Mock-only price recovery ended without 29-ticker readiness " +
                    "through 09:45. attempts={0} tickers={1}/29 exact0945={2}/29 " +
                    "max={3} latest_start={4}"
                ) -f
                ($MockPriceRecoveryHistory.Count - 1),
                $LastRecovery.today_tickers,
                $LastRecovery.exact_0945_tickers,
                $LastRecovery.max_datetime_today,
                $MockDataRecoveryLatestStart
            )
        }
    }

    foreach ($SnapshotSpec in $SnapshotSpecs) {
        $SourceManifestCandidate = "$($SnapshotSpec.Source).manifest.json"
        $TrustedSourceSnapshot = (
            $SnapshotSpec.Source -and
            (Test-Path -LiteralPath $SnapshotSpec.Source -PathType Leaf) -and
            (Test-Path -LiteralPath $SourceManifestCandidate -PathType Leaf)
        )
        if ($TrustedSourceSnapshot) {
            $SourceSnapshot = Get-FullPath -Path $SnapshotSpec.Source
            $SourceManifest = "$SourceSnapshot.manifest.json"
            $SourceVerification = Join-Path $MockLogs (
                "source_snapshot_{0}_verification.json" -f $SnapshotSpec.Cutoff.Replace(":", "")
            )
            Invoke-NativeChecked `
                -FilePath $RealPython `
                -Arguments @(
                    $RealSupport,
                    "snapshot",
                    "--source-db", $RealPriceDb,
                    "--dest-db", $SourceSnapshot,
                    "--date", $Date,
                    "--cutoff", $SnapshotSpec.Cutoff,
                    "--json-out", $SourceVerification
                ) `
                -WorkingDirectory $ProjectRoot `
                -PythonPathRoot $ProjectRoot `
                -Label "VERIFY SOURCE IMMUTABLE SNAPSHOT $($SnapshotSpec.Cutoff)" `
                -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
            Invoke-NativeChecked `
                -FilePath $RealPython `
                -Arguments @(
                    $RealSupport,
                    "sqlite-backup",
                    "--source-db", $SourceSnapshot,
                    "--dest-db", $SnapshotSpec.Destination
                ) `
                -WorkingDirectory $ProjectRoot `
                -PythonPathRoot $ProjectRoot `
                -Label "CONSISTENT MOCK SNAPSHOT BACKUP $($SnapshotSpec.Cutoff)" `
                -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
            $MockSnapshotManifest = "$($SnapshotSpec.Destination).manifest.json"
            Copy-Item -LiteralPath $SourceManifest -Destination $MockSnapshotManifest -Force
            $CopiedManifest = Get-Content -LiteralPath $MockSnapshotManifest -Raw |
                ConvertFrom-Json
            $SourceSnapshotHash = (
                Get-FileHash -LiteralPath $SourceSnapshot -Algorithm SHA256
            ).Hash.ToLower()
            $CopiedSnapshotHash = (
                Get-FileHash -LiteralPath $SnapshotSpec.Destination -Algorithm SHA256
            ).Hash.ToLower()
            $CopiedManifest.snapshot_sha256 = $CopiedSnapshotHash
            $CopiedManifest | Add-Member `
                -NotePropertyName source_snapshot_sha256 `
                -NotePropertyValue $SourceSnapshotHash `
                -Force
            $CopiedManifest.snapshot_action = "COPIED_VERIFIED_IMMUTABLE_SNAPSHOT"
            Write-JsonAtomic -Payload $CopiedManifest -Path $MockSnapshotManifest
            $CopiedVerification = Join-Path $MockLogs (
                "copied_snapshot_{0}_verification.json" -f $SnapshotSpec.Cutoff.Replace(":", "")
            )
            Invoke-NativeChecked `
                -FilePath $RealPython `
                -Arguments @(
                    $Support,
                    "snapshot",
                    "--source-db", $MockPriceDb,
                    "--dest-db", $SnapshotSpec.Destination,
                    "--date", $Date,
                    "--cutoff", $SnapshotSpec.Cutoff,
                    "--json-out", $CopiedVerification
                ) `
                -WorkingDirectory $MockRoot `
                -PythonPathRoot $MockRoot `
                -Label "VERIFY COPIED MOCK SNAPSHOT $($SnapshotSpec.Cutoff)" `
                -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        }
        else {
            Invoke-NativeChecked `
                -FilePath $RealPython `
                -Arguments @(
                    $Support,
                    "snapshot",
                    "--source-db", $MockPriceDb,
                    "--dest-db", $SnapshotSpec.Destination,
                    "--date", $Date,
                    "--cutoff", $SnapshotSpec.Cutoff
                ) `
                -WorkingDirectory $MockRoot `
                -PythonPathRoot $MockRoot `
                -Label "CREATE ISOLATED MOCK SNAPSHOT $($SnapshotSpec.Cutoff)" `
                -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        }
    }

    $StageModule = "RegimeTrading.scripts.step9_morning_v2_stage_runner"
    $StatusJson = Join-Path $MockLogs "${MockId}_status.json"
    $ManifestPath = Join-Path $MockRoot "MOCK_SESSION_DO_NOT_MERGE.json"
    $MockSnapshot0940Rel = "data\step9_morning_v2_snapshots\$Date\prices_through_0940.db"
    $MockSnapshot0945Rel = "data\step9_morning_v2_snapshots\$Date\prices_through_0945.db"
    $Manifest = [ordered]@{
        mock_id = $MockId
        session_date = $Date
        status = "MOCK_FALLBACK_RUNNING"
        evidence_status = "MOCK_REHEARSAL"
        evidence_eligible = $false
        source_project = $ProjectRoot
        isolated_mock_project = $MockRoot
        source_snapshot_0940 = $Snapshot0940
        source_snapshot_0945 = $Snapshot0945
        mock_snapshot_0940 = $MockSnapshot0940Abs
        mock_snapshot_0945 = $MockSnapshot0945Abs
        missing_trusted_source_snapshots = @($MissingTrustedSourceSnapshots)
        mock_price_recovery_required = [bool]$MockPriceRecoveryRequired
        mock_price_recovery_passed = [bool]$MockPriceRecoveryPassed
        mock_price_recovery_latest_start = $MockDataRecoveryLatestStart
        mock_price_recovery_attempts = @($MockPriceRecoveryHistory)
        real_ledger_merge = "PROHIBITED"
        production_routing = $false
        orders_enabled = $false
        created_at_stockholm = [System.TimeZoneInfo]::ConvertTime(
            [datetimeoffset]::Now,
            $TimeZone
        ).ToString("o")
        completed = $false
    }
    Write-JsonAtomic -Payload $Manifest -Path $ManifestPath

    Set-Location -LiteralPath $MockRoot
    $env:PYTHONPATH = $MockRoot
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    $ImportCode = @'
import importlib
import pathlib
import sys

mock_root = pathlib.Path(sys.argv[1]).resolve()
real_root = pathlib.Path(sys.argv[2]).resolve()
modules = [
    "RegimeTrading",
    "RegimeTrading.scripts.step9_morning_v2_stage_runner",
    "RegimeTrading.scripts.step9i_v2_core5_plus_holdout18_shadow_router",
    "RegimeTrading.scripts.step9l_v3_selected_strategy_shadow_engine",
    "RegimeTrading.scripts.step9s_prospective_contingency_shadow_v1",
    "RegimeTrading.scripts.step9r_v1_candidate_ranking_research",
    "RegimeTrading.scripts.step9t_prospective_regime_transition_archetype_v1",
    "RegimeTrading.scripts.step9u_prospective_contingency_selector_v1",
]
for name in modules:
    path = pathlib.Path(importlib.import_module(name).__file__).resolve()
    if mock_root not in (path, *path.parents):
        raise SystemExit(f"Import escaped mock root: {name} -> {path}")
for item in sys.path:
    if not item:
        continue
    path = pathlib.Path(item).resolve()
    if real_root in (path, *path.parents):
        relative = path.relative_to(real_root)
        if not relative.parts or relative.parts[0].lower() != ".venv":
            raise SystemExit(f"Real project path leaked into sys.path: {path}")
print("MOCK IMPORT ISOLATION: PASSED")
'@
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @("-c", $ImportCode, $MockRoot, $ProjectRoot) `
        -WorkingDirectory $MockRoot `
        -PythonPathRoot $MockRoot `
        -Label "VERIFY MOCK IMPORT ISOLATION" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null

    function Get-MockStatus {
        Invoke-NativeChecked `
            -FilePath $Python `
            -Arguments @($Support, "status", "--date", $Date, "--json-out", $StatusJson) `
            -WorkingDirectory $MockRoot `
            -PythonPathRoot $MockRoot `
            -Label "READ MOCK STATUS" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        return Get-Content -LiteralPath $StatusJson -Raw | ConvertFrom-Json
    }

    function Invoke-MockStage {
        param(
            [Parameter(Mandatory = $true)][string]$Stage,
            [Parameter(Mandatory = $true)][string[]]$Arguments
        )
        $StageJson = Join-Path $MockLogs (
            "mock_{0}_stage_result.json" -f $Stage
        )
        Invoke-NativeChecked `
            -FilePath $Python `
            -Arguments (
                @("-m", $StageModule, $Stage) +
                $Arguments +
                @("--json-out", $StageJson)
            ) `
            -WorkingDirectory $MockRoot `
            -PythonPathRoot $MockRoot `
            -Label ("MOCK " + $Stage.ToUpperInvariant()) `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    }

    $State = Get-MockStatus
    foreach ($Stage in @("step9i", "step9l", "step9s", "step9r", "step9t", "step9u")) {
        if ([bool]$State.$Stage.sealed) {
            Assert-MockStage -State $State -Stage $Stage
        }
    }

    if (-not [bool]$State.step9i.sealed) {
        Invoke-MockStage -Stage "step9i" -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfI,
            "--allow-late-reconstruction",
            "--source-db", $MockSnapshot0940Rel,
            "--ledger-db", "data\step9i_v2_shadow_ledger.db"
        )
    }
    if (-not [bool]$State.step9l.sealed) {
        Invoke-MockStage -Stage "step9l" -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfI,
            "--allow-late-reconstruction",
            "--source-db", $MockSnapshot0940Rel,
            "--ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db"
        )
    }
    $State = Get-MockStatus
    Assert-MockStage -State $State -Stage "step9i"
    Assert-MockStage -State $State -Stage "step9l"
    if ($State.step9i.primary_regime -ne $State.step9l.primary_regime) {
        throw "Step 9I and Step 9L disagree on the mock regime."
    }

    if (-not [bool]$State.step9s.sealed) {
        Invoke-MockStage -Stage "step9s" -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfS,
            "--allow-late-reconstruction",
            "--source-db", $MockSnapshot0940Rel,
            "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
            "--ledger-db", "data\step9s_prospective_contingency_shadow_v1.db"
        )
    }
    if (-not [bool]$State.step9t.sealed) {
        Invoke-MockStage -Stage "step9t" -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfT,
            "--allow-late-reconstruction",
            "--source-db", $MockSnapshot0945Rel,
            "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
            "--ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db"
        )
    }
    $State = Get-MockStatus
    Assert-MockStage -State $State -Stage "step9s"
    Assert-MockStage -State $State -Stage "step9t"

    if (-not [bool]$State.step9u.sealed) {
        Invoke-MockStage -Stage "step9u" -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfU,
            "--allow-late-reconstruction",
            "--step9t-ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db",
            "--ledger-db", "data\step9u_contingency_selector_prospective_shadow_v1.db"
        )
    }
    if (-not [bool]$State.step9r.sealed) {
        Invoke-MockStage -Stage "step9r" -Arguments @(
            "--date", $Date,
            "--source-db", $MockSnapshot0940Rel,
            "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
            "--research-db", "data\step9r_candidate_ranking_research_v1.db",
            "--ledger-db", "data\step9r_prospective_selector_shadow_v1.db"
        )
    }

    $FinalState = Get-MockStatus
    foreach ($Stage in @("step9i", "step9l", "step9s", "step9r", "step9t", "step9u")) {
        Assert-MockStage -State $FinalState -Stage $Stage
    }
    if (-not [bool]$FinalState.all_sealed) {
        throw "Mock fallback did not seal all six morning stages."
    }
    if (-not [bool]$FinalState.regime_consistent) {
        throw "Mock fallback stages disagree on the detected regime."
    }
    if ([bool]$FinalState.router_active -or [bool]$FinalState.orders_enabled) {
        throw "Mock fallback reported an unsafe routing or order state."
    }
    $CanonicalVerifyJson = Join-Path $MockLogs "${MockId}_canonical_verification.json"
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            $Support,
            "verify-mock",
            "--date", $Date,
            "--json-out", $CanonicalVerifyJson
        ) `
        -WorkingDirectory $MockRoot `
        -PythonPathRoot $MockRoot `
        -Label "CANONICAL MOCK COMPLETENESS VERIFICATION" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    $CanonicalVerification = Get-Content -LiteralPath $CanonicalVerifyJson -Raw |
        ConvertFrom-Json
    if (($CanonicalVerification.verification -ne "PASSED") -or
        (-not [bool]$CanonicalVerification.mock_complete)) {
        throw "Canonical mock completeness verification did not pass."
    }

    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            "-m", $StageModule, "export-all",
            "--date", $Date,
            "--step9i-ledger-db", "data\step9i_v2_shadow_ledger.db",
            "--step9l-ledger-db", "data\step9l_v3_selected_strategy_shadow_ledger.db",
            "--step9s-ledger-db", "data\step9s_prospective_contingency_shadow_v1.db",
            "--step9t-ledger-db", "data\step9t_regime_transition_archetype_prospective_v1.db",
            "--step9u-ledger-db", "data\step9u_contingency_selector_prospective_shadow_v1.db"
        ) `
        -WorkingDirectory $MockRoot `
        -PythonPathRoot $MockRoot `
        -Label "MOCK DEFERRED EXPORTS" `
        -TimeoutSeconds $ChildTimeoutSeconds `
        -NonCritical | Out-Null

    $Workbook = "data\powerbi\powerbi_mock_${Compact}.xlsx"
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            "-m", "RegimeTrading.scripts.step9q_powerbi_excel_feed",
            "--date", $Date,
            "--require-both-engines",
            "--output", $Workbook
        ) `
        -WorkingDirectory $MockRoot `
        -PythonPathRoot $MockRoot `
        -Label "MOCK STEP 9Q" `
        -TimeoutSeconds $ChildTimeoutSeconds `
        -NonCritical | Out-Null

    $Manifest.status = "MOCK_FALLBACK_COMPLETE"
    $Manifest.completed = $true
    $Manifest.completed_at_stockholm = [System.TimeZoneInfo]::ConvertTime(
        [datetimeoffset]::Now,
        $TimeZone
    ).ToString("o")
    $Manifest.final_status = $FinalState
    $Manifest.canonical_verification = $CanonicalVerification
    $Manifest.workbook = Join-Path $MockRoot $Workbook
    Write-JsonAtomic -Payload $Manifest -Path $ManifestPath
    $ResultStatus = "MOCK_FALLBACK_COMPLETE"
}
catch {
    $PrimaryError = $_
    if ($ManifestPath -and (Test-Path -LiteralPath (Split-Path -Parent $ManifestPath))) {
        try {
            $FailureManifest = [ordered]@{
                status = "MOCK_FALLBACK_FAILED"
                session_date = $Date
                evidence_status = "MOCK_REHEARSAL"
                completed = $false
                error = $_.Exception.Message
                missing_trusted_source_snapshots = @(
                    $MissingTrustedSourceSnapshots
                )
                mock_price_recovery_required = [bool]$MockPriceRecoveryRequired
                mock_price_recovery_passed = [bool]$MockPriceRecoveryPassed
                mock_price_recovery_attempts = @($MockPriceRecoveryHistory)
                router_active = $false
                orders_enabled = $false
            }
            Write-JsonAtomic -Payload $FailureManifest -Path $ManifestPath
        }
        catch { }
    }
}
finally {
    try {
        Stop-TrackedProcesses
    }
    catch {
        $CleanupError = $_
    }
    try { Set-Location -LiteralPath $PreviousLocation } catch { }
    if ($null -eq $OldPythonPath) {
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $OldPythonPath
    }
    if ($null -eq $OldNoUserSite) {
        Remove-Item Env:\PYTHONNOUSERSITE -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONNOUSERSITE = $OldNoUserSite
    }
    if ($null -eq $OldNoByteCode) {
        Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONDONTWRITEBYTECODE = $OldNoByteCode
    }
    try {
        $AfterState = Get-DatabaseState -Root $ProjectRoot
        Compare-DatabaseState -Before $BeforeState -After $AfterState
    }
    catch {
        $IntegrityError = $_
    }
}

$Result = [ordered]@{
    status = $ResultStatus
    session_date = $Date
    mock_project = $MockRoot
    manifest = $ManifestPath
    evidence_status = "MOCK_REHEARSAL"
    real_databases_unchanged = ($null -eq $IntegrityError)
    real_ledger_merge = "PROHIBITED"
    missing_trusted_source_snapshots = @($MissingTrustedSourceSnapshots)
    mock_price_recovery_required = [bool]$MockPriceRecoveryRequired
    mock_price_recovery_passed = [bool]$MockPriceRecoveryPassed
    mock_price_recovery_attempts = @($MockPriceRecoveryHistory)
    router_active = $false
    orders_enabled = $false
}
if ($PrimaryError) {
    $Result.error = $PrimaryError.Exception.Message
}
if ($IntegrityError) {
    $Result.integrity_error = $IntegrityError.Exception.Message
    $Result.status = "MOCK_FALLBACK_INTEGRITY_FAILURE"
}
if ($CleanupError) {
    $Result.cleanup_error = $CleanupError.Exception.Message
    $Result.status = "MOCK_FALLBACK_PROCESS_CLEANUP_FAILURE"
}
Write-JsonAtomic -Payload $Result -Path $ResultJson

if ($IntegrityError) {
    if ($PrimaryError) {
        if ($CleanupError) {
            throw (
                "$($PrimaryError.Exception.Message) Process cleanup also failed: " +
                "$($CleanupError.Exception.Message) Real-file integrity check " +
                "also failed: $($IntegrityError.Exception.Message)"
            )
        }
        throw "$($PrimaryError.Exception.Message) Real-file integrity check also failed: $($IntegrityError.Exception.Message)"
    }
    if ($CleanupError) {
        throw (
            "$($CleanupError.Exception.Message) Real-file integrity check also " +
            "failed: $($IntegrityError.Exception.Message)"
        )
    }
    throw $IntegrityError
}
if ($CleanupError) {
    if ($PrimaryError) {
        throw (
            "$($PrimaryError.Exception.Message) Process cleanup also failed: " +
            $CleanupError.Exception.Message
        )
    }
    throw $CleanupError
}
if ($PrimaryError) {
    throw $PrimaryError
}

Write-Host ""
Write-Host "STEP9 MORNING V2 MOCK FALLBACK: PASSED"
Write-Host "MOCK PROJECT: $MockRoot"
Write-Host "EVIDENCE STATUS: MOCK_REHEARSAL"
Write-Host "REAL DATABASES AND SIDECARS: BYTE-FOR-BYTE UNCHANGED"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
