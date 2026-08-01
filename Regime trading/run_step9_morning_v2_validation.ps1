param(
    [string]$ProjectRoot = "",
    [string]$ReferenceMockRoot = "",
    [ValidatePattern("^\d{4}-\d{2}-\d{2}$")]
    [string]$Date = "2026-07-30",
    [ValidateRange(1, 20)]
    [int]$Iterations = 10,
    [ValidateRange(30.0, 1800.0)]
    [double]$MaximumCriticalSeconds = 240.0,
    [ValidateRange(10.0, 120.0)]
    [double]$MaximumStartupBenchmarkSeconds = 30.0,
    [ValidateRange(30.0, 600.0)]
    [double]$MaximumWorkerReadySeconds = 240.0,
    [ValidateRange(30.0, 600.0)]
    [double]$MaximumCollectorBenchmarkSeconds = 180.0,
    [ValidateRange(30.0, 300.0)]
    [double]$PlannedCollectorSeconds = 90.0,
    [ValidateRange(0.0, 120.0)]
    [double]$MinimumLatestStartMarginSeconds = 10.0,
    [ValidateRange(120.0, 900.0)]
    [double]$MaximumModeledCriticalSeconds = 360.0,
    [ValidateRange(30, 3600)]
    [int]$ChildTimeoutSeconds = 900,
    [string]$ValidationBaseRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = $PSScriptRoot
}
if (-not $ReferenceMockRoot) {
    $ReferenceMockRoot = [Environment]::GetEnvironmentVariable("REGIME_TRADING_REFERENCE_MOCK_ROOT")
}
if (-not $ReferenceMockRoot) {
    $ReferenceMockRoot = Join-Path ([Environment]::GetFolderPath("UserProfile")) "S9M"
}

$StageRegistryPath = Join-Path $ProjectRoot "config\stage_registry.json"
if (-not (Test-Path -LiteralPath $StageRegistryPath -PathType Leaf)) {
    throw "Stage registry is missing: $StageRegistryPath"
}
$StageRegistry = Get-Content -LiteralPath $StageRegistryPath -Raw | ConvertFrom-Json
$PathConfigPath = Join-Path $ProjectRoot "config\paths.json"
if (-not (Test-Path -LiteralPath $PathConfigPath -PathType Leaf)) {
    throw "Path configuration is missing: $PathConfigPath"
}
$PathConfig = Get-Content -LiteralPath $PathConfigPath -Raw | ConvertFrom-Json
$ConfiguredDataRelative = [string]$PathConfig.data_dir
$StageLedgerPaths = @{}
foreach ($Property in $StageRegistry.ledger_paths.PSObject.Properties) {
    $StageLedgerPaths[$Property.Name] = [string]$Property.Value
}
function Get-ConfiguredLedgerPath {
    param([Parameter(Mandatory = $true)][string]$Stage)
    if (-not $StageLedgerPaths.ContainsKey($Stage)) {
        throw "Stage registry has no ledger path for: $Stage"
    }
    return Join-Path $ProjectRoot $StageLedgerPaths[$Stage]
}
$PersistentWorkerStages = @($StageRegistry.stage_groups.persistent_worker)
$DeadlineCriticalStages = @($StageRegistry.stage_groups.deadline_critical)
$NoncriticalStages = @($StageRegistry.stage_groups.noncritical)
$DeferredDiagnostics = @($StageRegistry.stage_groups.deferred_diagnostics)

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
    return [datetimeoffset]::new(
        $Local,
        $TimeZone.GetUtcOffset($Local)
    ).ToString("yyyy-MM-ddTHH:mm:sszzz")
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

function New-NativeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$PythonPathRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )
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
    return [pscustomobject]@{
        Label = $Label
        Process = $Process
        StdOutTask = $Process.StandardOutput.ReadToEndAsync()
        StdErrTask = $Process.StandardError.ReadToEndAsync()
        Started = [datetimeoffset]::Now
        Completed = $false
    }
}

function Complete-NativeProcess {
    param(
        [Parameter(Mandatory = $true)]$Job,
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 900
    )
    if ($Job.Completed) {
        return $Job.Result
    }
    $Elapsed = ([datetimeoffset]::Now - $Job.Started).TotalSeconds
    $RemainingSeconds = [math]::Max(1.0, $TimeoutSeconds - $Elapsed)
    $Completed = $Job.Process.WaitForExit([int][math]::Ceiling($RemainingSeconds * 1000))
    if (-not $Completed) {
        $TerminationError = $null
        try {
            if (-not $Job.Process.HasExited) {
                $Job.Process.Kill()
            }
            if (-not $Job.Process.WaitForExit($script:TerminationWaitMilliseconds)) {
                throw (
                    "$($Job.Label) process $($Job.Process.Id) did not exit " +
                    "within $($script:TerminationWaitMilliseconds) ms after Kill()."
                )
            }
        }
        catch {
            $TerminationError = $_
        }
        if ($null -eq $TerminationError) {
            $script:ActiveProcesses.Remove([string]$Job.Process.Id)
            try { $Job.Process.Dispose() } catch { }
        }
        else {
            throw (
                "$($Job.Label) exceeded its $TimeoutSeconds second timeout and " +
                "termination could not be proven: " +
                $TerminationError.Exception.Message
            )
        }
        throw "$($Job.Label) exceeded its $TimeoutSeconds second timeout."
    }
    $Ended = [datetimeoffset]$Job.Process.ExitTime
    $StdOut = $Job.StdOutTask.Result
    $StdErr = $Job.StdErrTask.Result
    $ExitCode = $Job.Process.ExitCode
    $script:ActiveProcesses.Remove([string]$Job.Process.Id)
    $Job.Process.Dispose()
    if (-not [string]::IsNullOrWhiteSpace($StdOut)) {
        Write-Host $StdOut.TrimEnd()
    }
    if (-not [string]::IsNullOrWhiteSpace($StdErr)) {
        Write-Host $StdErr.TrimEnd()
    }
    if ($ExitCode -ne 0) {
        throw "$($Job.Label) failed with exit code $ExitCode."
    }
    $Result = [pscustomobject]@{
        label = $Job.Label
        duration_seconds = [math]::Round(($Ended - $Job.Started).TotalSeconds, 3)
        completed_at = $Ended
        exit_code = $ExitCode
    }
    $Job | Add-Member -NotePropertyName Result -NotePropertyValue $Result -Force
    $Job.Completed = $true
    return $Result
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$PythonPathRoot,
        [Parameter(Mandatory = $true)][string]$Label,
        [int]$TimeoutSeconds = 900
    )
    Write-Host ""
    Write-Host "=== $Label ==="
    $Job = New-NativeProcess `
        -FilePath $FilePath `
        -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -PythonPathRoot $PythonPathRoot `
        -Label $Label
    return Complete-NativeProcess -Job $Job -TimeoutSeconds $TimeoutSeconds
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
    $DataRoot = Join-Path $Root $script:ConfiguredDataRelative
    if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
        return $State
    }
    foreach ($File in @(Get-ChildItem -LiteralPath $DataRoot -Recurse -File |
        Where-Object {
            $_.Name -match '\.(?:db|sqlite|sqlite3)(?:-wal|-shm|-journal)?$'
        } |
        Sort-Object FullName)) {
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
        [Parameter(Mandatory = $true)]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $BeforeKeys = @($Before.Keys | Sort-Object)
    $AfterKeys = @($After.Keys | Sort-Object)
    $Added = @($AfterKeys | Where-Object { $BeforeKeys -notcontains $_ })
    $Removed = @($BeforeKeys | Where-Object { $AfterKeys -notcontains $_ })
    $Changed = @(
        foreach ($Key in $BeforeKeys) {
            if ($AfterKeys -notcontains $Key) {
                continue
            }
            if (($Before[$Key].sha256 -ne $After[$Key].sha256) -or
                ([long]$Before[$Key].length -ne [long]$After[$Key].length)) {
                $Key
            }
        }
    )
    if (($Added.Count -gt 0) -or ($Removed.Count -gt 0) -or ($Changed.Count -gt 0)) {
        $Message = (
            "{0} database or sidecar state changed. Added=[{1}] Removed=[{2}] Changed=[{3}]" -f
            $Label,
            ($Added -join ", "),
            ($Removed -join ", "),
            ($Changed -join ", ")
        )
        throw $Message
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

$ParsedDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
    $Date,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]::None,
    [ref]$ParsedDate
)) {
    throw "Validation session date is invalid: $Date"
}

$ProjectRoot = Get-FullPath -Path $ProjectRoot
$ReferenceMockRoot = Get-FullPath -Path $ReferenceMockRoot
foreach ($RequiredRoot in @($ProjectRoot, $ReferenceMockRoot)) {
    if (-not (Test-Path -LiteralPath $RequiredRoot -PathType Container)) {
        throw "Validation source root not found: $RequiredRoot"
    }
}
if (-not $ValidationBaseRoot) {
    $ValidationBaseRoot = Join-Path $env:USERPROFILE "S9V"
}
$ValidationBaseRoot = Get-FullPath -Path $ValidationBaseRoot
foreach ($ProtectedRoot in @($ProjectRoot, $ReferenceMockRoot)) {
    if ((Test-PathWithin -Path $ValidationBaseRoot -Root $ProtectedRoot) -or
        (Test-PathWithin -Path $ProtectedRoot -Root $ValidationBaseRoot)) {
        throw "Validation base and source roots must be completely separate directory trees."
    }
}
if (Test-Path -LiteralPath $ValidationBaseRoot) {
    $BaseItem = Get-Item -LiteralPath $ValidationBaseRoot -Force
    if (($BaseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Validation base must not be a junction or symbolic link."
    }
}
else {
    New-Item -ItemType Directory -Path $ValidationBaseRoot -Force | Out-Null
}

$RealPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RealSupport = Join-Path $ProjectRoot "tools\step9_morning_v2_support.py"
foreach ($Path in @($RealPython, $RealSupport)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required validation dependency is missing: $Path"
    }
}

$TimeZone = Get-StockholmTimeZone
$AsOfI = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:45:20" -TimeZone $TimeZone
$AsOfS = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:46:10" -TimeZone $TimeZone
$AsOfT = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:48:00" -TimeZone $TimeZone
$AsOfU = ConvertTo-StockholmTimestamp -SessionDate $ParsedDate -Clock "09:48:10" -TimeZone $TimeZone

$ProjectBefore = Get-DatabaseState -Root $ProjectRoot
$ReferenceBefore = Get-DatabaseState -Root $ReferenceMockRoot
$PrimaryError = $null
$IntegrityError = $null
$CleanupError = $null
$PreviousLocation = Get-Location
$OldPythonPath = $env:PYTHONPATH
$OldNoUserSite = $env:PYTHONNOUSERSITE
$OldNoByteCode = $env:PYTHONDONTWRITEBYTECODE
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ValidationRoot = Join-Path $ValidationBaseRoot (
    "VALIDATE_${Stamp}_$([guid]::NewGuid().ToString('N').Substring(0,8))"
)
$ReportPath = ""
$ValidationPassed = $false

try {
    if (Test-Path -LiteralPath $ValidationRoot) {
        throw "Unique validation destination unexpectedly exists: $ValidationRoot"
    }
    New-Item -ItemType Directory -Path $ValidationRoot | Out-Null
    $null = & robocopy `
        $ProjectRoot `
        $ValidationRoot `
        /E /COPY:DAT /DCOPY:T /R:1 /W:1 /XJ `
        /NFL /NDL /NJH /NJS /NP `
        /XD ".venv" ".git" "__pycache__" ".pytest_cache" "logs" `
        /XF "*.pyc" "*.pyo" `
            "*.db" "*.db-wal" "*.db-shm" "*.db-journal" `
            "*.sqlite" "*.sqlite-wal" "*.sqlite-shm" "*.sqlite-journal" `
            "*.sqlite3" "*.sqlite3-wal" "*.sqlite3-shm" "*.sqlite3-journal"
    if ($LASTEXITCODE -gt 7) {
        throw "Validation clone failed with robocopy exit code $LASTEXITCODE."
    }

    $Python = $RealPython
    $Support = Join-Path $ValidationRoot "tools\step9_morning_v2_support.py"
    $StageModule = "RegimeTrading.scripts.step9_morning_v2_stage_runner"
    $WorkerModule = "RegimeTrading.scripts.step9_morning_v2_persistent_worker"
    $Logs = Join-Path $ValidationRoot "logs"
    $ReferenceDir = Join-Path $ValidationRoot "data\validation_reference"
    New-Item -ItemType Directory -Path $Logs -Force | Out-Null
    New-Item -ItemType Directory -Path $ReferenceDir -Force | Out-Null
    $ReportPath = Join-Path $Logs "step9_morning_v2_validation_${Stamp}.json"

    $ProjectDatabases = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "data") -Recurse -File |
        Where-Object { $_.Name -match '\.(?:db|sqlite|sqlite3)$' } |
        Sort-Object FullName)
    foreach ($Database in $ProjectDatabases) {
        $Relative = $Database.FullName.Substring($ProjectRoot.Length).TrimStart([char]92, [char]47)
        $Destination = Join-Path $ValidationRoot $Relative
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
            -Label "CONSISTENT VALIDATION BACKUP: $Relative" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    }

    $ReferenceNames = @(
        "step9i_shadow_intraday_prices.db",
        "step9s_prospective_contingency_shadow_v1.db",
        "step9r_candidate_ranking_research_v1.db",
        "step9r_prospective_selector_shadow_v1.db",
        "step9t_regime_transition_archetype_prospective_v1.db",
        "step9u_contingency_selector_prospective_shadow_v1.db"
    )
    $ReferenceSources = @{
        "step9r_candidate_ranking_research_v1.db" = "data\ledgers\research\step9r_candidate_ranking_research_v1.db"
        "step9r_prospective_selector_shadow_v1.db" = "data\ledgers\prospective\step9r_prospective_selector_shadow_v1.db"
    }
    $ReferenceCopies = [ordered]@{}
    foreach ($Name in $ReferenceNames) {
        $SourceRelative = if ($ReferenceSources.ContainsKey($Name)) { $ReferenceSources[$Name] } else { "data\$Name" }
        $Source = Join-Path $ReferenceMockRoot $SourceRelative
        if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
            throw "Reference validation database is missing: $Source"
        }
        $Destination = Join-Path $ReferenceDir $Name
        Invoke-NativeChecked `
            -FilePath $RealPython `
            -Arguments @(
                $RealSupport,
                "sqlite-backup",
                "--source-db", $Source,
                "--dest-db", $Destination
            ) `
            -WorkingDirectory $ProjectRoot `
            -PythonPathRoot $ProjectRoot `
            -Label "CONSISTENT REFERENCE BACKUP: $Name" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        $ReferenceCopies[$Name] = $Destination
    }

    $AuthenticFixtureCsv = Join-Path $ProjectRoot (
        "tests\fixtures\step9_morning_v2_20260730_prices.csv"
    )
    $AuthenticFixtureManifest = Join-Path $ProjectRoot (
        "tests\fixtures\step9_morning_v2_20260730_prices.manifest.json"
    )
    $AuthenticFixtureDb = Join-Path $ReferenceDir (
        "authentic_step9_morning_v2_20260730_0945_prices.db"
    )
    foreach ($FixturePath in @(
        $AuthenticFixtureCsv,
        $AuthenticFixtureManifest
    )) {
        if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
            throw "Authentic validation fixture is missing: $FixturePath"
        }
    }
    $FixtureResultJson = Join-Path $Logs (
        "authentic_20260730_price_fixture.json"
    )
    Invoke-NativeChecked `
        -FilePath $RealPython `
        -Arguments @(
            $RealSupport,
            "fixture-db",
            "--csv", $AuthenticFixtureCsv,
            "--fixture-manifest", $AuthenticFixtureManifest,
            "--dest-db", $AuthenticFixtureDb,
            "--json-out", $FixtureResultJson
        ) `
        -WorkingDirectory $ProjectRoot `
        -PythonPathRoot $ProjectRoot `
        -Label "MATERIALIZE AUTHENTIC JULY 30 MORNING FIXTURE" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    $AuthenticFixtureResult = Get-Content `
        -LiteralPath $FixtureResultJson `
        -Raw | ConvertFrom-Json
    if (
        $AuthenticFixtureResult.status -ne
        "AUTHENTIC_VALIDATION_PRICE_FIXTURE_MATERIALIZED"
    ) {
        throw "Authentic July 30 price fixture did not validate."
    }

    $RealIReference = Join-Path $ReferenceDir "reference_step9i_v2_shadow_ledger.db"
    $RealLReference = Join-Path $ReferenceDir "reference_step9l_v3_shadow_ledger.db"
    foreach ($Spec in @(
        [pscustomobject]@{
            Source = Get-ConfiguredLedgerPath -Stage "step9i"
            Destination = $RealIReference
            Label = "STEP 9I"
        },
        [pscustomobject]@{
            Source = Get-ConfiguredLedgerPath -Stage "step9l"
            Destination = $RealLReference
            Label = "STEP 9L"
        }
    )) {
        if (-not (Test-Path -LiteralPath $Spec.Source -PathType Leaf)) {
            throw "$($Spec.Label) reference ledger is missing: $($Spec.Source)"
        }
        Invoke-NativeChecked `
            -FilePath $RealPython `
            -Arguments @(
                $RealSupport,
                "sqlite-backup",
                "--source-db", $Spec.Source,
                "--dest-db", $Spec.Destination
            ) `
            -WorkingDirectory $ProjectRoot `
            -PythonPathRoot $ProjectRoot `
            -Label "CONSISTENT $($Spec.Label) REFERENCE BACKUP" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    }

    Set-Location -LiteralPath $ValidationRoot
    $env:PYTHONPATH = $ValidationRoot
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    $ImportCode = @'
import importlib
import pathlib
import sys

validation_root = pathlib.Path(sys.argv[1]).resolve()
real_root = pathlib.Path(sys.argv[2]).resolve()
modules = [
    "RegimeTrading",
    "RegimeTrading.scripts.step9_morning_v2_stage_runner",
    "RegimeTrading.scripts.step9_morning_v2_persistent_worker",
    "RegimeTrading.scripts.step9i_v2_core5_plus_holdout18_shadow_router",
    "RegimeTrading.scripts.step9l_v3_selected_strategy_shadow_engine",
    "RegimeTrading.scripts.step9s_prospective_contingency_shadow_v1",
    "RegimeTrading.scripts.step9r_v1_candidate_ranking_research",
    "RegimeTrading.scripts.step9t_prospective_regime_transition_archetype_v1",
    "RegimeTrading.scripts.step9u_prospective_contingency_selector_v1",
]
for name in modules:
    path = pathlib.Path(importlib.import_module(name).__file__).resolve()
    if validation_root not in (path, *path.parents):
        raise SystemExit(f"Import escaped validation root: {name} -> {path}")
for item in sys.path:
    if not item:
        continue
    path = pathlib.Path(item).resolve()
    if real_root in (path, *path.parents):
        relative = path.relative_to(real_root)
        if not relative.parts or relative.parts[0].lower() != ".venv":
            raise SystemExit(f"Real project path leaked into sys.path: {path}")
print("VALIDATION IMPORT ISOLATION: PASSED")
'@
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @("-c", $ImportCode, $ValidationRoot, $ProjectRoot) `
        -WorkingDirectory $ValidationRoot `
        -PythonPathRoot $ValidationRoot `
        -Label "VERIFY VALIDATION IMPORT ISOLATION" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null

    Write-Host ""
    Write-Host "=== BENCHMARK LIVE STARTUP CHECKS IN ISOLATION ==="
    $RuntimeManifest = Join-Path $ValidationRoot (
        "config\step9_morning_v2_runtime_manifest.json"
    )
    $StartupRuntimeJson = Join-Path $Logs "startup_runtime_manifest.json"
    $StartupStatusJson = Join-Path $Logs "startup_status.json"
    $StartupWatch = [Diagnostics.Stopwatch]::StartNew()
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            $Support,
            "runtime-manifest",
            "--manifest", $RuntimeManifest,
            "--root", $ValidationRoot,
            "--json-out", $StartupRuntimeJson
        ) `
        -WorkingDirectory $ValidationRoot `
        -PythonPathRoot $ValidationRoot `
        -Label "ISOLATED STARTUP RUNTIME CHECK" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            $Support,
            "status",
            "--date", $Date,
            "--json-out", $StartupStatusJson
        ) `
        -WorkingDirectory $ValidationRoot `
        -PythonPathRoot $ValidationRoot `
        -Label "ISOLATED STARTUP STATUS CHECK" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    $StartupWatch.Stop()
    $StartupBenchmarkSeconds = [math]::Round(
        $StartupWatch.Elapsed.TotalSeconds,
        3
    )
    if ($StartupBenchmarkSeconds -gt $MaximumStartupBenchmarkSeconds) {
        throw ((
            "Isolated startup checks took {0} seconds, above the {1} " +
            "second prewarm budget."
        ) -f $StartupBenchmarkSeconds, $MaximumStartupBenchmarkSeconds)
    }

    Write-Host ""
    Write-Host "=== BENCHMARK COLLECTOR AGAINST ISOLATED DATABASE ==="
    $CollectorBenchmarkDir = Join-Path $ValidationRoot (
        "data\v2_validation\collector_benchmark"
    )
    New-Item -ItemType Directory -Path $CollectorBenchmarkDir -Force |
        Out-Null
    $CollectorBenchmarkDb = Join-Path $CollectorBenchmarkDir "prices.db"
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            $Support,
            "sqlite-backup",
            "--source-db", $ReferenceCopies["step9i_shadow_intraday_prices.db"],
            "--dest-db", $CollectorBenchmarkDb
        ) `
        -WorkingDirectory $ValidationRoot `
        -PythonPathRoot $ValidationRoot `
        -Label "PREPARE ISOLATED COLLECTOR BENCHMARK DATABASE" `
        -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
    $CollectorWatch = [Diagnostics.Stopwatch]::StartNew()
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            "-m",
            "RegimeTrading.scripts.collect_step9i_shadow_data",
            "--days", "2",
            "--interval", "5m",
            "--db", $CollectorBenchmarkDb,
            "--skip-bootstrap"
        ) `
        -WorkingDirectory $ValidationRoot `
        -PythonPathRoot $ValidationRoot `
        -Label "ISOLATED COLLECTOR BENCHMARK" `
        -TimeoutSeconds ([int][math]::Ceiling(
            $MaximumCollectorBenchmarkSeconds
        )) | Out-Null
    $CollectorWatch.Stop()
    $CollectorBenchmarkSeconds = [math]::Round(
        $CollectorWatch.Elapsed.TotalSeconds,
        3
    )
    if ($CollectorBenchmarkSeconds -gt $MaximumCollectorBenchmarkSeconds) {
        throw ((
            "Isolated collector benchmark took {0} seconds, above the {1} " +
            "second limit."
        ) -f $CollectorBenchmarkSeconds, $MaximumCollectorBenchmarkSeconds)
    }
    $CollectorPlanningSeconds = [math]::Max(
        $PlannedCollectorSeconds,
        $CollectorBenchmarkSeconds
    )

    function Start-ValidationStage {
        param(
            [Parameter(Mandatory = $true)][string]$Stage,
            [Parameter(Mandatory = $true)][string[]]$Arguments,
            [Parameter(Mandatory = $true)][int]$Iteration
        )
        Write-Host ""
        Write-Host "STARTING ITERATION $Iteration $($Stage.ToUpperInvariant())"
        return New-NativeProcess `
            -FilePath $Python `
            -Arguments (@("-m", $StageModule, $Stage) + $Arguments) `
            -WorkingDirectory $ValidationRoot `
            -PythonPathRoot $ValidationRoot `
            -Label "ITERATION $Iteration $($Stage.ToUpperInvariant())"
    }


    function Start-ValidationWorker {
        param(
            [Parameter(Mandatory = $true)][string]$Stage,
            [Parameter(Mandatory = $true)][int]$Iteration
        )
        $WorkerDirectory = Join-Path $Logs "iteration_${Iteration}_workers"
        New-Item -ItemType Directory -Path $WorkerDirectory -Force | Out-Null
        $ReadyJson = Join-Path $WorkerDirectory "${Stage}_ready.json"
        $RequestJson = Join-Path $WorkerDirectory "${Stage}_request.json"
        $ResultJson = Join-Path $WorkerDirectory "${Stage}_result.json"
        foreach ($Path in @($ReadyJson, $RequestJson, $ResultJson)) {
            if (Test-Path -LiteralPath $Path) {
                throw "Validation worker protocol path already exists: $Path"
            }
        }
        Write-Host ""
        Write-Host "STARTING ITERATION $Iteration $($Stage.ToUpperInvariant()) PERSISTENT WORKER"
        $Job = New-NativeProcess `
            -FilePath $Python `
            -Arguments @(
                "-m", $WorkerModule,
                "--stage", $Stage,
                "--mode", "validation",
                "--project-root", $ValidationRoot,
                "--ready-json", $ReadyJson,
                "--request-json", $RequestJson,
                "--result-json", $ResultJson,
                "--request-timeout-seconds", "$ChildTimeoutSeconds"
            ) `
            -WorkingDirectory $ValidationRoot `
            -PythonPathRoot $ValidationRoot `
            -Label "ITERATION $Iteration $($Stage.ToUpperInvariant()) PERSISTENT WORKER"
        $Job | Add-Member -NotePropertyName Stage -NotePropertyValue $Stage -Force
        $Job | Add-Member -NotePropertyName ReadyJson -NotePropertyValue $ReadyJson -Force
        $Job | Add-Member -NotePropertyName RequestJson -NotePropertyValue $RequestJson -Force
        $Job | Add-Member -NotePropertyName ResultJson -NotePropertyValue $ResultJson -Force
        $Job | Add-Member -NotePropertyName ReleasedAt -NotePropertyValue $null -Force
        $Job | Add-Member -NotePropertyName ReadyPayload -NotePropertyValue $null -Force
        return $Job
    }

    function Wait-ValidationWorkerReady {
        param(
            [Parameter(Mandatory = $true)]$Job,
            [Parameter(Mandatory = $true)][int]$Iteration
        )
        $Deadline = [datetimeoffset]::Now.AddSeconds($ChildTimeoutSeconds)
        while ([datetimeoffset]::Now -lt $Deadline) {
            if (Test-Path -LiteralPath $Job.ReadyJson -PathType Leaf) {
                $Payload = Get-Content -LiteralPath $Job.ReadyJson -Raw | ConvertFrom-Json
                if (
                    [string]$Payload.status -ne "STEP9_MORNING_V2_PERSISTENT_WORKER_READY" -or
                    [string]$Payload.stage -ne [string]$Job.Stage -or
                    [string]$Payload.mode -ne "validation" -or
                    [bool]$Payload.router_active -or
                    [bool]$Payload.orders_enabled
                ) {
                    throw "Iteration $Iteration $($Job.Stage) worker readiness failed semantic validation."
                }
                $ReadySeconds = [double]$Payload.ready_seconds
                if ($ReadySeconds -gt $MaximumWorkerReadySeconds) {
                    throw (
                        "Iteration {0} {1} worker needed {2} seconds to become ready, above the {3} second limit." -f
                        $Iteration,
                        $Job.Stage,
                        ([math]::Round($ReadySeconds, 3)),
                        $MaximumWorkerReadySeconds
                    )
                }
                $Job.ReadyPayload = $Payload
                Write-Host (
                    "ITERATION {0} {1} WORKER READY IN {2} SECONDS" -f
                    $Iteration,
                    $Job.Stage.ToUpperInvariant(),
                    ([math]::Round($ReadySeconds, 3))
                )
                return $Payload
            }
            if ($Job.Process.HasExited) {
                [void](Complete-NativeProcess -Job $Job -TimeoutSeconds 1)
                throw "Iteration $Iteration $($Job.Stage) worker exited before readiness."
            }
            Start-Sleep -Milliseconds 100
        }
        throw "Iteration $Iteration $($Job.Stage) worker did not become ready within $ChildTimeoutSeconds seconds."
    }

    function Release-ValidationWorker {
        param(
            [Parameter(Mandatory = $true)]$Job,
            [Parameter(Mandatory = $true)][string]$SessionDate,
            [Parameter(Mandatory = $true)][string]$AsOf,
            [Parameter(Mandatory = $true)][string]$SourceDb,
            [Parameter(Mandatory = $true)][string]$LedgerDb,
            [Parameter(Mandatory = $true)][string]$SourceSha256,
            [Parameter(Mandatory = $true)][int]$Iteration
        )
        $RequestId = "validation_${Iteration}_$($Job.Stage)_$([guid]::NewGuid().ToString('N'))"
        Write-JsonAtomic -Payload ([ordered]@{
            protocol = "STEP9_MORNING_V2_PERSISTENT_WORKER_V1"
            request_id = $RequestId
            stage = [string]$Job.Stage
            mode = "validation"
            session_date = $SessionDate
            as_of = $AsOf
            allow_late_reconstruction = $true
            source_db = $SourceDb
            ledger_db = $LedgerDb
            source_sha256 = $SourceSha256.ToLower()
            defer_core_regime_sensitivity = ([string]$Job.Stage -eq "step9l")
            router_active = $false
            orders_enabled = $false
        }) -Path $Job.RequestJson
        $Job.ReleasedAt = [datetimeoffset]::Now
        $Job | Add-Member -NotePropertyName RequestId -NotePropertyValue $RequestId -Force
    }

    function Complete-ValidationWorker {
        param(
            [Parameter(Mandatory = $true)]$Job,
            [Parameter(Mandatory = $true)][int]$Iteration
        )
        if ($null -eq $Job.ReleasedAt) {
            throw "Iteration $Iteration $($Job.Stage) worker was never released."
        }
        $NativeResult = Complete-NativeProcess -Job $Job -TimeoutSeconds $ChildTimeoutSeconds
        if (-not (Test-Path -LiteralPath $Job.ResultJson -PathType Leaf)) {
            throw "Iteration $Iteration $($Job.Stage) worker returned without a result JSON."
        }
        $Payload = Get-Content -LiteralPath $Job.ResultJson -Raw | ConvertFrom-Json
        if (
            [string]$Payload.status -ne "STEP9_MORNING_V2_PERSISTENT_WORKER_STAGE_PASSED" -or
            [string]$Payload.stage -ne [string]$Job.Stage -or
            [string]$Payload.request_id -ne [string]$Job.RequestId -or
            (
                [string]$Job.Stage -eq "step9l" -and
                -not [bool]$Payload.core_regime_sensitivity_deferred
            ) -or
            [bool]$Payload.router_active -or
            [bool]$Payload.orders_enabled
        ) {
            throw "Iteration $Iteration $($Job.Stage) worker result failed semantic validation."
        }
        return [pscustomobject]@{
            label = $NativeResult.label
            duration_seconds = [math]::Round(
                ($NativeResult.completed_at - $Job.ReleasedAt).TotalSeconds,
                3
            )
            completed_at = $NativeResult.completed_at
            exit_code = $NativeResult.exit_code
            worker_ready_seconds = [double]$Job.ReadyPayload.ready_seconds
            worker_pid = [int]$Payload.worker_pid
        }
    }

    $IterationResults = @()
    for ($Iteration = 1; $Iteration -le $Iterations; $Iteration++) {
        Write-Host ""
        Write-Host "================ VALIDATION ITERATION $Iteration / $Iterations ================"
        $SnapshotDir = Join-Path $ValidationRoot "data\v2_validation\iteration_$Iteration\snapshots"
        $LedgerDir = Join-Path $ValidationRoot "data\v2_validation\iteration_$Iteration\ledgers"
        New-Item -ItemType Directory -Path $SnapshotDir -Force | Out-Null
        New-Item -ItemType Directory -Path $LedgerDir -Force | Out-Null
        $Snapshot0940Abs = Join-Path $SnapshotDir "prices_0940.db"
        $Snapshot0945Abs = Join-Path $SnapshotDir "prices_0945.db"
        $Snapshot0940Rel = $Snapshot0940Abs.Substring($ValidationRoot.Length).TrimStart([char]92, [char]47)
        $Snapshot0945Rel = $Snapshot0945Abs.Substring($ValidationRoot.Length).TrimStart([char]92, [char]47)
        $SourcePrice0940 = $ReferenceCopies["step9i_shadow_intraday_prices.db"]
        $SourcePrice0945 = $AuthenticFixtureDb

        $IRel = "data\v2_validation\iteration_$Iteration\ledgers\i.db"
        $LRel = "data\v2_validation\iteration_$Iteration\ledgers\l.db"
        $SRel = "data\v2_validation\iteration_$Iteration\ledgers\s.db"
        $RRel = "data\v2_validation\iteration_$Iteration\ledgers\r.db"
        $TRel = "data\v2_validation\iteration_$Iteration\ledgers\t.db"
        $URel = "data\v2_validation\iteration_$Iteration\ledgers\u.db"

        $IJob = Start-ValidationWorker -Stage "step9i" -Iteration $Iteration
        $LJob = Start-ValidationWorker -Stage "step9l" -Iteration $Iteration
        $IReady = Wait-ValidationWorkerReady -Job $IJob -Iteration $Iteration
        $LReady = Wait-ValidationWorkerReady -Job $LJob -Iteration $Iteration
        $WorkerReadySeconds = [math]::Max(
            [double]$IReady.ready_seconds,
            [double]$LReady.ready_seconds
        )

        $IterationStart = [datetimeoffset]::Now
        Invoke-NativeChecked `
            -FilePath $Python `
            -Arguments @(
                $Support,
                "snapshot",
                "--source-db", $SourcePrice0940,
                "--dest-db", $Snapshot0940Abs,
                "--date", $Date,
                "--cutoff", "09:40"
            ) `
            -WorkingDirectory $ValidationRoot `
            -PythonPathRoot $ValidationRoot `
            -Label "ITERATION $Iteration CREATE 09:40 SNAPSHOT" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        Invoke-NativeChecked `
            -FilePath $Python `
            -Arguments @(
                $Support,
                "snapshot",
                "--source-db", $SourcePrice0945,
                "--dest-db", $Snapshot0945Abs,
                "--date", $Date,
                "--cutoff", "09:45"
            ) `
            -WorkingDirectory $ValidationRoot `
            -PythonPathRoot $ValidationRoot `
            -Label "ITERATION $Iteration CREATE 09:45 SNAPSHOT" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        $SnapshotComplete = [datetimeoffset]::Now
        $Snapshot0940Hash = (
            Get-FileHash -LiteralPath $Snapshot0940Abs -Algorithm SHA256
        ).Hash.ToLower()
        $DecisionStart = [datetimeoffset]::Now

        # Give Step 9L exclusive release priority because it unlocks every
        # downstream decision stage. Step 9I remains pre-imported and waiting.
        Release-ValidationWorker `
            -Job $LJob `
            -SessionDate $Date `
            -AsOf $AsOfI `
            -SourceDb $Snapshot0940Rel `
            -LedgerDb $LRel `
            -SourceSha256 $Snapshot0940Hash `
            -Iteration $Iteration
        $LResult = Complete-ValidationWorker -Job $LJob -Iteration $Iteration

        # Release Step 9I immediately after 9L seals. It can then execute while
        # the downstream 9S/9R/9T/9U path proceeds without blocking on 9I.
        Release-ValidationWorker `
            -Job $IJob `
            -SessionDate $Date `
            -AsOf $AsOfI `
            -SourceDb $Snapshot0940Rel `
            -LedgerDb $IRel `
            -SourceSha256 $Snapshot0940Hash `
            -Iteration $Iteration

        $SJob = Start-ValidationStage -Stage "step9s" -Iteration $Iteration -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfS,
            "--allow-late-reconstruction",
            "--source-db", $Snapshot0940Rel,
            "--step9l-ledger-db", $LRel,
            "--ledger-db", $SRel
        )
        $TJob = Start-ValidationStage -Stage "step9t" -Iteration $Iteration -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfT,
            "--allow-late-reconstruction",
            "--source-db", $Snapshot0945Rel,
            "--step9l-ledger-db", $LRel,
            "--ledger-db", $TRel
        )
        $RJob = Start-ValidationStage -Stage "step9r" -Iteration $Iteration -Arguments @(
            "--date", $Date,
            "--source-db", $Snapshot0940Rel,
            "--step9l-ledger-db", $LRel,
            "--research-db", $ReferenceCopies["step9r_candidate_ranking_research_v1.db"],
            "--ledger-db", $RRel
        )
        $TResult = Complete-NativeProcess -Job $TJob -TimeoutSeconds $ChildTimeoutSeconds
        $UJob = Start-ValidationStage -Stage "step9u" -Iteration $Iteration -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfU,
            "--allow-late-reconstruction",
            "--step9t-ledger-db", $TRel,
            "--ledger-db", $URel
        )
        $UResult = Complete-NativeProcess -Job $UJob -TimeoutSeconds $ChildTimeoutSeconds
        $SResult = Complete-NativeProcess -Job $SJob -TimeoutSeconds $ChildTimeoutSeconds
        $CriticalComplete = @(
            $LResult.completed_at,
            $SResult.completed_at,
            $TResult.completed_at,
            $UResult.completed_at
        ) | Sort-Object -Descending | Select-Object -First 1
        $RResult = Complete-NativeProcess -Job $RJob -TimeoutSeconds $ChildTimeoutSeconds
        $IResult = Complete-ValidationWorker -Job $IJob -Iteration $Iteration
        $SensitivityJob = Start-ValidationStage -Stage "step9l-sensitivity" -Iteration $Iteration -Arguments @(
            "--date", $Date,
            "--as-of", $AsOfI,
            "--source-db", $Snapshot0940Rel,
            "--ledger-db", $LRel
        )
        $SensitivityResult = Complete-NativeProcess -Job $SensitivityJob -TimeoutSeconds $ChildTimeoutSeconds
        $AllComplete = @(
            $IResult.completed_at,
            $LResult.completed_at,
            $SResult.completed_at,
            $RResult.completed_at,
            $TResult.completed_at,
            $UResult.completed_at,
            $SensitivityResult.completed_at
        ) | Sort-Object -Descending | Select-Object -First 1

        $CriticalSeconds = [math]::Round(($CriticalComplete - $IterationStart).TotalSeconds, 3)
        $DecisionCriticalSeconds = [math]::Round(
            ($CriticalComplete - $DecisionStart).TotalSeconds,
            3
        )
        $AllStageSeconds = [math]::Round(($AllComplete - $IterationStart).TotalSeconds, 3)
        $SnapshotSeconds = [math]::Round(($SnapshotComplete - $IterationStart).TotalSeconds, 3)
        $Step9SCompletionSeconds = [math]::Round(
            ($SResult.completed_at - $IterationStart).TotalSeconds,
            3
        )
        if ($CriticalSeconds -gt $MaximumCriticalSeconds) {
            throw "Critical path $CriticalSeconds seconds exceeds budget $MaximumCriticalSeconds seconds."
        }

        # Model the actual live dependency graph from the frozen 09:45:02
        # collector start. Validation runs historical stages without wall-clock
        # sleeps, so this calculation applies the real 09:48 gate and each
        # frozen latest-start boundary to the measured stage durations.
        $DecisionStartOffset = $CollectorPlanningSeconds + $SnapshotSeconds
        $Step9LCompleteOffset = (
            $DecisionStartOffset + [double]$LResult.duration_seconds
        )
        $Step9IStartOffset = $Step9LCompleteOffset
        $Step9ICompleteOffset = (
            $Step9IStartOffset + [double]$IResult.duration_seconds
        )
        $Step9SStartOffset = $Step9LCompleteOffset
        $Step9SCompleteOffset = (
            $Step9SStartOffset + [double]$SResult.duration_seconds
        )
        $Step9RStartOffset = $Step9LCompleteOffset
        $Step9RCompleteOffset = (
            $Step9RStartOffset + [double]$RResult.duration_seconds
        )
        $Step9TStartOffset = [math]::Max(
            178.0,
            $Step9LCompleteOffset
        )
        $Step9TCompleteOffset = (
            $Step9TStartOffset + [double]$TResult.duration_seconds
        )
        $Step9UStartOffset = $Step9TCompleteOffset
        $Step9UCompleteOffset = (
            $Step9UStartOffset + [double]$UResult.duration_seconds
        )
        $Step9LSensitivityStartOffset = [math]::Max(
            $Step9ICompleteOffset,
            [math]::Max($Step9RCompleteOffset, [math]::Max($Step9SCompleteOffset, $Step9UCompleteOffset))
        )
        $Step9LSensitivityCompleteOffset = (
            $Step9LSensitivityStartOffset + [double]$SensitivityResult.duration_seconds
        )
        $ModeledCriticalSeconds = $Step9LSensitivityCompleteOffset
        $Step9SLatestStartMargin = 263.0 - $Step9SStartOffset
        $Step9TLatestStartMargin = 263.0 - $Step9TStartOffset
        $Step9ULatestStartMargin = 288.0 - $Step9UStartOffset
        $MinimumModeledMargin = @(
            $Step9SLatestStartMargin,
            $Step9TLatestStartMargin,
            $Step9ULatestStartMargin
        ) | Measure-Object -Minimum | Select-Object -ExpandProperty Minimum
        if ([double]$MinimumModeledMargin -lt $MinimumLatestStartMarginSeconds) {
            throw ((
                "Modeled live latest-start margin {0} seconds is below the " +
                "required {1} seconds. S={2} T={3} U={4}"
            ) -f
                ([math]::Round([double]$MinimumModeledMargin, 3)),
                $MinimumLatestStartMarginSeconds,
                ([math]::Round($Step9SLatestStartMargin, 3)),
                ([math]::Round($Step9TLatestStartMargin, 3)),
                ([math]::Round($Step9ULatestStartMargin, 3))
            )
        }
        if ($ModeledCriticalSeconds -gt $MaximumModeledCriticalSeconds) {
            throw ((
                "Modeled collector-inclusive critical path {0} seconds " +
                "exceeds budget {1} seconds."
            ) -f
                ([math]::Round($ModeledCriticalSeconds, 3)),
                $MaximumModeledCriticalSeconds
            )
        }

        $CompareJson = Join-Path $Logs "iteration_${Iteration}_comparison.json"
        Invoke-NativeChecked `
            -FilePath $Python `
            -Arguments @(
                $Support,
                "compare-validation",
                "--date", $Date,
                "--candidate-i", (Join-Path $ValidationRoot $IRel),
                "--candidate-l", (Join-Path $ValidationRoot $LRel),
                "--candidate-s", (Join-Path $ValidationRoot $SRel),
                "--candidate-r", (Join-Path $ValidationRoot $RRel),
                "--candidate-t", (Join-Path $ValidationRoot $TRel),
                "--candidate-u", (Join-Path $ValidationRoot $URel),
                "--reference-i", $RealIReference,
                "--reference-l", $RealLReference,
                "--reference-s", $ReferenceCopies["step9s_prospective_contingency_shadow_v1.db"],
                "--reference-r", $ReferenceCopies["step9r_prospective_selector_shadow_v1.db"],
                "--reference-t", $ReferenceCopies["step9t_regime_transition_archetype_prospective_v1.db"],
                "--reference-u", $ReferenceCopies["step9u_contingency_selector_prospective_shadow_v1.db"],
                "--json-out", $CompareJson
            ) `
            -WorkingDirectory $ValidationRoot `
            -PythonPathRoot $ValidationRoot `
            -Label "COMPARE ITERATION $Iteration TO FROZEN REFERENCES" `
            -TimeoutSeconds $ChildTimeoutSeconds | Out-Null
        $Comparison = Get-Content -LiteralPath $CompareJson -Raw | ConvertFrom-Json
        if ($Comparison.status -ne "PASSED") {
            throw "Iteration $Iteration did not reproduce the reference ledgers."
        }

        $IterationResults += [pscustomobject]@{
            iteration = $Iteration
            collector_benchmarked = $true
            collector_benchmark_seconds = $CollectorBenchmarkSeconds
            collector_planning_seconds = $CollectorPlanningSeconds
            timing_scope = "step9l_core_seal_then_downstream_with_deferred_sensitivity_completion"
            worker_ready_seconds = [math]::Round($WorkerReadySeconds, 3)
            step9i_worker_ready_seconds = [math]::Round([double]$IReady.ready_seconds, 3)
            step9l_worker_ready_seconds = [math]::Round([double]$LReady.ready_seconds, 3)
            snapshot_seconds = $SnapshotSeconds
            step9s_completion_from_iteration_start_seconds = $Step9SCompletionSeconds
            deadline_critical_l_s_t_u_seconds = $CriticalSeconds
            deadline_critical_after_snapshots_seconds = $DecisionCriticalSeconds
            critical_budget_margin_seconds = [math]::Round(
                $MaximumCriticalSeconds - $CriticalSeconds,
                3
            )
            all_stage_and_diagnostic_seconds = $AllStageSeconds
            step9i_seconds = $IResult.duration_seconds
            step9l_seconds = $LResult.duration_seconds
            step9s_seconds = $SResult.duration_seconds
            noncritical_step9r_seconds = $RResult.duration_seconds
            step9t_seconds = $TResult.duration_seconds
            step9u_seconds = $UResult.duration_seconds
            step9l_sensitivity_seconds = $SensitivityResult.duration_seconds
            modeled_collector_inclusive_critical_seconds = [math]::Round(
                $ModeledCriticalSeconds,
                3
            )
            modeled_step9i_start_offset_seconds = [math]::Round(
                $Step9IStartOffset,
                3
            )
            modeled_step9s_start_offset_seconds = [math]::Round(
                $Step9SStartOffset,
                3
            )
            modeled_step9r_start_offset_seconds = [math]::Round(
                $Step9RStartOffset,
                3
            )
            modeled_step9r_complete_offset_seconds = [math]::Round(
                $Step9RCompleteOffset,
                3
            )
            modeled_step9t_start_offset_seconds = [math]::Round(
                $Step9TStartOffset,
                3
            )
            modeled_step9u_start_offset_seconds = [math]::Round(
                $Step9UStartOffset,
                3
            )
            step9s_latest_start_margin_seconds = [math]::Round(
                $Step9SLatestStartMargin,
                3
            )
            step9t_latest_start_margin_seconds = [math]::Round(
                $Step9TLatestStartMargin,
                3
            )
            step9u_latest_start_margin_seconds = [math]::Round(
                $Step9ULatestStartMargin,
                3
            )
            comparison_status = $Comparison.status
            comparison_file = $CompareJson
            authentic_0945_fixture_id = (
                $AuthenticFixtureResult.fixture_id
            )
            authentic_0945_fixture_csv_sha256 = (
                $AuthenticFixtureResult.fixture_csv_sha256
            )
        }
    }

    $WorstWorkerReady = ($IterationResults |
        Measure-Object -Property worker_ready_seconds -Maximum).Maximum
    $WorstCritical = ($IterationResults |
        Measure-Object -Property deadline_critical_l_s_t_u_seconds -Maximum).Maximum
    $WorstModeledCritical = ($IterationResults |
        Measure-Object -Property modeled_collector_inclusive_critical_seconds -Maximum).Maximum
    $WorstLatestStartMargin = [math]::Min(
        [double](($IterationResults |
            Measure-Object -Property step9s_latest_start_margin_seconds -Minimum).Minimum),
        [math]::Min(
            [double](($IterationResults |
                Measure-Object -Property step9t_latest_start_margin_seconds -Minimum).Minimum),
            [double](($IterationResults |
                Measure-Object -Property step9u_latest_start_margin_seconds -Minimum).Minimum)
        )
    )
    $Report = [ordered]@{
        status = "STEP9_MORNING_V2_ISOLATED_EQUIVALENCE_VALIDATION_PASSED"
        qualification_scope = "isolated_equivalence_collector_benchmark_and_live_schedule_model"
        startup_benchmark_seconds = $StartupBenchmarkSeconds
        maximum_startup_benchmark_seconds = $MaximumStartupBenchmarkSeconds
        persistent_worker_protocol = "STEP9_MORNING_V2_PERSISTENT_WORKER_V1"
        maximum_worker_ready_seconds = $MaximumWorkerReadySeconds
        worst_worker_ready_seconds = [double]$WorstWorkerReady
        collector_benchmarked = $true
        collector_benchmark_seconds = $CollectorBenchmarkSeconds
        maximum_collector_benchmark_seconds = $MaximumCollectorBenchmarkSeconds
        collector_planning_seconds = $CollectorPlanningSeconds
        validated_at_stockholm = [System.TimeZoneInfo]::ConvertTime(
            [datetimeoffset]::Now,
            $TimeZone
        ).ToString("o")
        session_date = $Date
        iterations = $Iterations
        maximum_critical_seconds = $MaximumCriticalSeconds
        maximum_modeled_critical_seconds = $MaximumModeledCriticalSeconds
        minimum_latest_start_margin_seconds = $MinimumLatestStartMarginSeconds
        # Registry contract: persistent_worker_stages = @("step9i", "step9l")
        # Registry contract: deadline_critical_stages = @("step9l", "step9s", "step9t", "step9u")
        # Registry contract: noncritical_stages = @("step9i", "step9r", "step9l_sensitivity")
        # Registry contract: deferred_diagnostics = @("step9l_core_regime_sensitivity")
        persistent_worker_stages = $PersistentWorkerStages
        deadline_critical_stages = $DeadlineCriticalStages
        noncritical_stages = $NoncriticalStages
        deferred_diagnostics = $DeferredDiagnostics
        authentic_0945_fixture = [ordered]@{
            fixture_id = $AuthenticFixtureResult.fixture_id
            fixture_csv_sha256 = (
                $AuthenticFixtureResult.fixture_csv_sha256
            )
            source_archive_sha256 = (
                "e8c7b619295dfe4fef3991b42532f4f2b65cfe6a3771ee870153f5d4a97d9a38"
            )
            point_in_time_rows = $AuthenticFixtureResult.today_rows
            exact_0945_tickers = (
                $AuthenticFixtureResult.exact_0945_tickers
            )
        }
        worst_critical_seconds = [double]$WorstCritical
        worst_modeled_collector_inclusive_critical_seconds = [double]$WorstModeledCritical
        worst_latest_start_margin_seconds = [double]$WorstLatestStartMargin
        measured_margin_seconds = [math]::Round(
            $MaximumCriticalSeconds - [double]$WorstCritical,
            3
        )
        child_timeout_seconds = $ChildTimeoutSeconds
        results = $IterationResults
        validation_root = $ValidationRoot
        router_active = $false
        orders_enabled = $false
        project_databases_modified = $false
        reference_databases_modified = $false
    }
    Write-JsonAtomic -Payload $Report -Path $ReportPath
    $ValidationPassed = $true
}
catch {
    $PrimaryError = $_
    if ($ReportPath) {
        try {
            Write-JsonAtomic -Payload ([ordered]@{
                status = "STEP9_MORNING_V2_ISOLATED_EQUIVALENCE_VALIDATION_FAILED"
                qualification_scope = "isolated_equivalence_collector_benchmark_and_live_schedule_model"
                collector_benchmarked = (
                    $null -ne (Get-Variable -Name CollectorBenchmarkSeconds `
                        -ErrorAction SilentlyContinue)
                )
                session_date = $Date
                validation_root = $ValidationRoot
                error = $_.Exception.Message
                router_active = $false
                orders_enabled = $false
            }) -Path $ReportPath
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
        Compare-DatabaseState `
            -Before $ProjectBefore `
            -After (Get-DatabaseState -Root $ProjectRoot) `
            -Label "Real project"
        Compare-DatabaseState `
            -Before $ReferenceBefore `
            -After (Get-DatabaseState -Root $ReferenceMockRoot) `
            -Label "Reference mock"
    }
    catch {
        $IntegrityError = $_
    }
}

if ($IntegrityError) {
    if ($PrimaryError) {
        if ($CleanupError) {
            throw (
                "$($PrimaryError.Exception.Message) Process cleanup also failed: " +
                "$($CleanupError.Exception.Message) Source integrity check also " +
                "failed: $($IntegrityError.Exception.Message)"
            )
        }
        throw "$($PrimaryError.Exception.Message) Source integrity check also failed: $($IntegrityError.Exception.Message)"
    }
    if ($CleanupError) {
        throw (
            "$($CleanupError.Exception.Message) Source integrity check also " +
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
if (-not $ValidationPassed) {
    throw "Validation ended without a passing result."
}

Write-Host ""
Write-Host "STEP9 MORNING V2 ISOLATED EQUIVALENCE VALIDATION: PASSED"
Write-Host "ITERATIONS: $Iterations"
Write-Host "STARTUP BENCHMARK SECONDS: $StartupBenchmarkSeconds"
Write-Host "COLLECTOR BENCHMARK SECONDS: $CollectorBenchmarkSeconds"
Write-Host "COLLECTOR PLANNING SECONDS: $CollectorPlanningSeconds"
Write-Host "WORST MODELED CRITICAL SECONDS: $WorstModeledCritical"
Write-Host "WORST LATEST-START MARGIN SECONDS: $WorstLatestStartMargin"
Write-Host (
    "QUALIFICATION SCOPE: ISOLATED EQUIVALENCE, COLLECTOR BENCHMARK, " +
    "AND LIVE SCHEDULE MODEL"
)
Write-Host "VALIDATION ROOT: $ValidationRoot"
Write-Host "REPORT: $ReportPath"
Write-Host "REAL AND REFERENCE DATABASES: BYTE-FOR-BYTE UNCHANGED"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
