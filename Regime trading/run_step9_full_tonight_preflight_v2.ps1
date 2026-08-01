param(
    [string]$NextSessionDate = "",
    [switch]$SkipFullSuite,
    [switch]$SkipValidation,
    [ValidateRange(10, 20)]
    [int]$ValidationIterations = 10,
    [ValidateRange(30.0, 1800.0)]
    [double]$MaximumCriticalSeconds = 240.0,
    [string]$ReferenceMockRoot = "",
    [string]$RuntimeManifest = "",
    [ValidateRange(30, 3600)]
    [int]$ChildTimeoutSeconds = 900,
    [ValidateRange(300, 14400)]
    [int]$ValidationTimeoutSeconds = 7200,
    [ValidateRange(300, 14400)]
    [int]$FullSuiteTimeoutSeconds = 7200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd([char]92, [char]47)
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
        [ValidateRange(1, 14400)][int]$TimeoutSeconds = 900
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
        throw "$Label failed with exit code $ExitCode."
    }
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

$Root = Get-FullPath -Path $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Support = Join-Path $Root "tools\step9_morning_v2_support.py"
$PathConfig = Get-Content -LiteralPath (Join-Path $Root "config\paths.json") -Raw | ConvertFrom-Json
$LogsValue = [string]$PathConfig.log_dir
$Logs = if ([System.IO.Path]::IsPathRooted($LogsValue)) {
    [System.IO.Path]::GetFullPath($LogsValue)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $Root $LogsValue))
}
$ConfiguredReferenceMockRoot = [Environment]::GetEnvironmentVariable("REGIME_TRADING_REFERENCE_MOCK_ROOT")
if (-not $ReferenceMockRoot) {
    $ReferenceMockRoot = $ConfiguredReferenceMockRoot
}
if (-not $ReferenceMockRoot) {
    $ReferenceMockRoot = Join-Path ([Environment]::GetFolderPath("UserProfile")) "S9M"
}
if (-not $RuntimeManifest) {
    $RuntimeManifest = Join-Path $Root "config\step9_morning_v2_runtime_manifest.json"
}
$RuntimeManifest = Get-FullPath -Path $RuntimeManifest
$InstalledRuntimeManifest = Get-FullPath -Path (
    Join-Path $Root "config\step9_morning_v2_runtime_manifest.json"
)
if (-not $RuntimeManifest.Equals(
    $InstalledRuntimeManifest,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Qualification requires the installed audited runtime manifest: $InstalledRuntimeManifest"
}
$TimeZone = Get-StockholmTimeZone
$StockholmNow = [System.TimeZoneInfo]::ConvertTime([datetimeoffset]::Now, $TimeZone)
if (-not $NextSessionDate) {
    $NextSessionDate = $StockholmNow.Date.AddDays(1).ToString("yyyy-MM-dd")
}
$ParsedNextDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
    $NextSessionDate,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]::None,
    [ref]$ParsedNextDate
)) {
    throw "Next session date is invalid: $NextSessionDate"
}
if ($ParsedNextDate.Date -le $StockholmNow.Date) {
    throw "Next session date must be after the current Stockholm date."
}
if ($ParsedNextDate.DayOfWeek -in @(
    [DayOfWeek]::Saturday,
    [DayOfWeek]::Sunday
)) {
    throw (
        "Next session date is a weekend. Supply the next intended market " +
        "session explicitly with -NextSessionDate."
    )
}
$SessionNoon = [datetime]::new(
    $ParsedNextDate.Year,
    $ParsedNextDate.Month,
    $ParsedNextDate.Day,
    12,
    0,
    0,
    [System.DateTimeKind]::Unspecified
)
if ($TimeZone.IsInvalidTime($SessionNoon)) {
    throw "The next session date has an invalid Stockholm local time."
}
$SessionOffset = $TimeZone.GetUtcOffset($SessionNoon)
$DiagnosticOnly = $SkipFullSuite.IsPresent -or $SkipValidation.IsPresent

$Required = @(
    "run_step9_full_live_morning_v2.ps1",
    "run_step9_morning_mock_fallback_v2.ps1",
    "run_step9_morning_v2_validation.ps1",
    "run_step9_full_tonight_preflight_v2.ps1",
    "register_step9_morning_v2_tasks.ps1",
    "tools\step9_morning_v2_support.py",
    "RegimeTrading\scripts\step9_morning_v2_stage_runner.py",
    "config\step9_morning_v2_runtime_manifest.json",
    "config\step9s_prospective_contingency_shadow_v1.json",
    "config\step9r_candidate_ranking_research_v1.json",
    "config\step9t_prospective_regime_transition_archetype_v1.json",
    "config\step9u_prospective_contingency_selector_v1.json"
)

$BeforeState = Get-DatabaseState -Root $Root
$PrimaryError = $null
$IntegrityError = $null
$CleanupError = $null
$PreviousLocation = Get-Location
$OldPythonPath = $env:PYTHONPATH
$OldNoUserSite = $env:PYTHONNOUSERSITE
$OldNoByteCode = $env:PYTHONDONTWRITEBYTECODE
$PushedLocation = $false
$Marker = ""
$PreflightPassed = $false
$RuntimeBefore = $null
$RuntimeAfter = $null

try {
    Push-Location -LiteralPath $Root
    $PushedLocation = $true
    New-Item -ItemType Directory -Path $Logs -Force | Out-Null
    $env:PYTHONPATH = $Root
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Project Python is missing: $Python"
    }
    $Missing = @($Required | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $Root $_) -PathType Leaf)
    })
    if ($Missing.Count -gt 0) {
        throw "Required Morning V2 files are missing: $($Missing -join ', ')"
    }
    if (-not (Test-Path -LiteralPath $RuntimeManifest -PathType Leaf)) {
        throw "Runtime manifest is missing: $RuntimeManifest"
    }

    Write-Host "Stockholm now: $($StockholmNow.ToString('o'))"
    Write-Host "Next session: $NextSessionDate"
    Write-Host "Session UTC offset: $($SessionOffset.ToString())"

    $PendingReboot = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    if ($PendingReboot) {
        Write-Warning "Windows reports a pending reboot. Reboot tonight, not during the morning session."
    }

    $Cpu = $null
    try {
        $Cpu = Get-CimInstance Win32_Processor -ErrorAction Stop |
            Select-Object -First 1 CurrentClockSpeed, MaxClockSpeed
    }
    catch {
        Write-Warning "CPU clock query was unavailable: $($_.Exception.Message)"
    }
    if ($null -ne $Cpu) {
        Write-Host "CPU clock: $($Cpu.CurrentClockSpeed) / $($Cpu.MaxClockSpeed) MHz"
        if ([int]$Cpu.CurrentClockSpeed -lt 600) {
            throw "CPU appears severely throttled below 600 MHz."
        }
    }

    $DriveName = [System.IO.Path]::GetPathRoot($Root).TrimEnd([char]58, [char]92)
    $Drive = Get-PSDrive -Name $DriveName -ErrorAction Stop
    Write-Host "Free disk: $([math]::Round($Drive.Free / 1GB, 2)) GB"
    if ($Drive.Free -lt 2GB) {
        throw "Less than 2 GB free disk space remains."
    }
    if (@(Get-Process EXCEL -ErrorAction SilentlyContinue).Count -gt 0) {
        Write-Warning "Excel is open. Close Step 9 workbooks before tomorrow morning."
    }

    Write-Host ""
    Write-Host "=== WINDOWS POWERSHELL PARSER CHECKS ==="
    $PowerShellFiles = @(
        "run_step9_full_live_morning_v2.ps1",
        "run_step9_morning_mock_fallback_v2.ps1",
        "run_step9_morning_v2_validation.ps1",
        "run_step9_full_tonight_preflight_v2.ps1",
        "register_step9_morning_v2_tasks.ps1"
    )
    foreach ($Relative in $PowerShellFiles) {
        $Path = Join-Path $Root $Relative
        $Tokens = $null
        $ParseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $Path,
            [ref]$Tokens,
            [ref]$ParseErrors
        ) | Out-Null
        $Errors = @($ParseErrors)
        if ($Errors.Count -gt 0) {
            $Messages = @($Errors | ForEach-Object { $_.Message }) -join " | "
            throw "PowerShell parser failed for ${Relative}: $Messages"
        }
        Write-Host "PARSED: $Relative"
    }

    $RuntimeBeforeJson = Join-Path $Logs (
        "step9_morning_v2_runtime_before_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    )
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            $Support,
            "runtime-manifest",
            "--manifest", $RuntimeManifest,
            "--root", $Root,
            "--json-out", $RuntimeBeforeJson
        ) `
        -WorkingDirectory $Root `
        -PythonPathRoot $Root `
        -Label "VERIFY AUDITED RUNTIME MANIFEST BEFORE TESTS" `
        -TimeoutSeconds $ChildTimeoutSeconds
    $RuntimeBefore = Get-Content -LiteralPath $RuntimeBeforeJson -Raw | ConvertFrom-Json
    if ($RuntimeBefore.status -ne "STEP9_MORNING_V2_RUNTIME_COMPATIBILITY_PASSED") {
        throw "The pre-test runtime manifest check did not pass."
    }

    $ManifestPayload = Get-Content -LiteralPath $RuntimeManifest -Raw | ConvertFrom-Json
    $RuntimeClosureRequired = @(
        "run_step9_full_live_morning_v2.ps1",
        "run_step9_morning_mock_fallback_v2.ps1",
        "run_step9_morning_v2_validation.ps1",
        "run_step9_full_tonight_preflight_v2.ps1",
        "register_step9_morning_v2_tasks.ps1",
        "tools/step9_morning_v2_support.py",
        "RegimeTrading/scripts/step9_morning_v2_stage_runner.py",
        "RegimeTrading/scripts/step9_morning_v2_persistent_worker.py",
        "data/archives/freezes/step9s_historical_contingency_replay_v1/freeze_v1/9b045fb10e196a38/step9s_historical_output_freeze_summary.json",
        "data/archives/freezes/step9u_historical_contingency_selector_v1/freeze_8042ad803be28ccf/STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1_FREEZE_MANIFEST.json",
        "config/step9s_prospective_contingency_shadow_v1.json",
        "config/step9r_candidate_ranking_research_v1.json",
        "config/step9t_prospective_regime_transition_archetype_v1.json",
        "config/step9u_prospective_contingency_selector_v1.json"
    )
    $ManifestNames = @($ManifestPayload.files.PSObject.Properties |
        ForEach-Object { $_.Name.Replace([char]92, [char]47) })
    $MissingClosure = @($RuntimeClosureRequired |
        Where-Object { $ManifestNames -notcontains $_ })
    if ($MissingClosure.Count -gt 0) {
        throw "Runtime manifest does not close over all V2 dependencies: $($MissingClosure -join ', ')"
    }
    $PythonFiles = @()
    foreach ($Property in $ManifestPayload.files.PSObject.Properties) {
        if ($Property.Name.EndsWith(".py", [System.StringComparison]::OrdinalIgnoreCase)) {
            $PythonFiles += Join-Path $Root $Property.Name
        }
    }
    $PythonFiles += @(
        (Join-Path $Root "tools\step9_morning_v2_support.py"),
        (Join-Path $Root "RegimeTrading\scripts\step9_morning_v2_stage_runner.py")
    )
    $PythonFiles = @($PythonFiles | Sort-Object -Unique)
    $CompileJson = Join-Path $Logs (
        "step9_morning_v2_compile_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    )
    $CompileArguments = @($Support, "compile-files")
    foreach ($PythonFile in $PythonFiles) {
        $CompileArguments += @("--path", $PythonFile)
    }
    $CompileArguments += @("--json-out", $CompileJson)
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments $CompileArguments `
        -WorkingDirectory $Root `
        -PythonPathRoot $Root `
        -Label "READ-ONLY COMPILE AUDITED PYTHON RUNTIME" `
        -TimeoutSeconds $ChildTimeoutSeconds

    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            "-c",
            "from RegimeTrading.scripts import step9_morning_v2_stage_runner, step9_morning_v2_persistent_worker, step9i_v2_core5_plus_holdout18_shadow_router, step9l_v3_selected_strategy_shadow_engine, step9s_prospective_contingency_shadow_v1, step9r_v1_candidate_ranking_research, step9t_prospective_regime_transition_archetype_v1, step9u_prospective_contingency_selector_v1; print('STEP9_MORNING_V2_IMPORTS: PASSED')"
        ) `
        -WorkingDirectory $Root `
        -PythonPathRoot $Root `
        -Label "MORNING V2 IMPORT SMOKE TEST" `
        -TimeoutSeconds $ChildTimeoutSeconds

    $FocusedTests = @(
        "tests/test_step9_morning_v2_support.py",
        "tests/test_step9_morning_v2_persistent_worker.py",
        "tests/test_step9_morning_v2_deferred_sensitivity.py",
        "tests/test_step9_morning_v2_install_contract.py",
        "tests/test_step9i_v2_core5_plus_holdout18.py",
        "tests/test_step9l_v3_selected_strategy_shadow_engine.py",
        "tests/test_step9s_prospective_contingency_shadow_v1.py",
        "tests/test_step9r_v1_candidate_ranking_research.py",
        "tests/test_step9t_prospective_regime_transition_archetype_v1.py",
        "tests/test_step9u_prospective_contingency_selector_v1.py"
    )
    $MissingTests = @($FocusedTests | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $Root $_) -PathType Leaf)
    })
    if ($MissingTests.Count -gt 0) {
        throw "Focused test files are missing: $($MissingTests -join ', ')"
    }
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments (@("-m", "pytest", "-q", "-p", "no:cacheprovider") + $FocusedTests) `
        -WorkingDirectory $Root `
        -PythonPathRoot $Root `
        -Label "MORNING V2 FOCUSED TESTS" `
        -TimeoutSeconds $FullSuiteTimeoutSeconds

    if (-not $SkipValidation) {
        $PowerShellExe = Join-Path $PSHOME "powershell.exe"
        if (-not (Test-Path -LiteralPath $PowerShellExe -PathType Leaf)) {
            throw "Windows PowerShell executable is missing: $PowerShellExe"
        }
        Invoke-NativeChecked `
            -FilePath $PowerShellExe `
            -Arguments @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", (Join-Path $Root "run_step9_morning_v2_validation.ps1"),
                "-ProjectRoot", $Root,
                "-ReferenceMockRoot", (Get-FullPath -Path $ReferenceMockRoot),
                "-Date", "2026-07-30",
                "-Iterations", ([string]$ValidationIterations),
                "-MaximumCriticalSeconds", ([string]::Format(
                    [System.Globalization.CultureInfo]::InvariantCulture,
                    "{0}",
                    $MaximumCriticalSeconds
                )),
                "-ChildTimeoutSeconds", ([string]$ChildTimeoutSeconds)
            ) `
            -WorkingDirectory $Root `
            -PythonPathRoot $Root `
            -Label "TIMED ISOLATED JULY 30 EQUIVALENCE VALIDATION" `
            -TimeoutSeconds $ValidationTimeoutSeconds
    }
    else {
        Write-Warning "Timed isolated validation was skipped. This run cannot qualify V2."
    }

    if (-not $SkipFullSuite) {
        Invoke-NativeChecked `
            -FilePath $Python `
            -Arguments @("-m", "pytest", "-q", "-p", "no:cacheprovider", "tests") `
            -WorkingDirectory $Root `
            -PythonPathRoot $Root `
            -Label "FULL PROJECT COMPATIBILITY SUITE" `
            -TimeoutSeconds $FullSuiteTimeoutSeconds
    }
    else {
        Write-Warning "The full test suite was skipped. This run cannot qualify V2."
    }

    $RuntimeAfterJson = Join-Path $Logs (
        "step9_morning_v2_runtime_after_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    )
    Invoke-NativeChecked `
        -FilePath $Python `
        -Arguments @(
            $Support,
            "runtime-manifest",
            "--manifest", $RuntimeManifest,
            "--root", $Root,
            "--json-out", $RuntimeAfterJson
        ) `
        -WorkingDirectory $Root `
        -PythonPathRoot $Root `
        -Label "VERIFY AUDITED RUNTIME MANIFEST AFTER TESTS" `
        -TimeoutSeconds $ChildTimeoutSeconds
    $RuntimeAfter = Get-Content -LiteralPath $RuntimeAfterJson -Raw | ConvertFrom-Json
    if ($RuntimeAfter.status -ne "STEP9_MORNING_V2_RUNTIME_COMPATIBILITY_PASSED") {
        throw "The post-test runtime manifest check did not pass."
    }

    $Marker = Join-Path $Logs (
        "step9_full_tonight_preflight_v2_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    )
    $Status = if ($DiagnosticOnly) {
        "STEP9_MORNING_V2_PREFLIGHT_DIAGNOSTIC_ONLY"
    }
    else {
        "STEP9_MORNING_V2_PREFLIGHT_QUALIFIED"
    }
    $Payload = [ordered]@{
        status = $Status
        qualified = (-not $DiagnosticOnly)
        created_at_stockholm = [System.TimeZoneInfo]::ConvertTime(
            [datetimeoffset]::Now,
            $TimeZone
        ).ToString("o")
        next_session_date = $NextSessionDate
        next_session_utc_offset = $SessionOffset.ToString()
        validation_run = (-not $SkipValidation.IsPresent)
        validation_iterations = if ($SkipValidation) { 0 } else { $ValidationIterations }
        full_suite_run = (-not $SkipFullSuite.IsPresent)
        runtime_manifest = $RuntimeManifest
        runtime_manifest_sha256 = (
            Get-FileHash -LiteralPath $RuntimeManifest -Algorithm SHA256
        ).Hash.ToLower()
        runtime_before = $RuntimeBefore
        runtime_after = $RuntimeAfter
        database_integrity_check_pending = $true
        router_active = $false
        orders_enabled = $false
    }
    Write-JsonAtomic -Payload $Payload -Path $Marker
    $PreflightPassed = -not $DiagnosticOnly
}
catch {
    $PrimaryError = $_
}
finally {
    try {
        Stop-TrackedProcesses
    }
    catch {
        $CleanupError = $_
    }
    if ($PushedLocation) {
        try { Pop-Location } catch { try { Set-Location -LiteralPath $PreviousLocation } catch { } }
    }
    else {
        try { Set-Location -LiteralPath $PreviousLocation } catch { }
    }
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
            -Before $BeforeState `
            -After (Get-DatabaseState -Root $Root)
    }
    catch {
        $IntegrityError = $_
    }
}

if ($Marker -and (Test-Path -LiteralPath $Marker -PathType Leaf)) {
    try {
        $FinalPayload = Get-Content -LiteralPath $Marker -Raw | ConvertFrom-Json
        $FinalPayload.database_integrity_check_pending = $false
        $FinalPayload | Add-Member `
            -NotePropertyName databases_and_sidecars_unchanged `
            -NotePropertyValue ($null -eq $IntegrityError) `
            -Force
        if ($IntegrityError) {
            $FinalPayload.status = "STEP9_MORNING_V2_PREFLIGHT_INTEGRITY_FAILED"
            $FinalPayload.qualified = $false
            $FinalPayload | Add-Member `
                -NotePropertyName integrity_error `
                -NotePropertyValue $IntegrityError.Exception.Message `
                -Force
        }
        Write-JsonAtomic -Payload $FinalPayload -Path $Marker
    }
    catch {
        if (-not $PrimaryError) {
            $PrimaryError = $_
        }
    }
}

if ($IntegrityError) {
    if ($PrimaryError) {
        if ($CleanupError) {
            throw (
                "$($PrimaryError.Exception.Message) Process cleanup also failed: " +
                "$($CleanupError.Exception.Message) Database integrity check also " +
                "failed: $($IntegrityError.Exception.Message)"
            )
        }
        throw "$($PrimaryError.Exception.Message) Database integrity check also failed: $($IntegrityError.Exception.Message)"
    }
    if ($CleanupError) {
        throw (
            "$($CleanupError.Exception.Message) Database integrity check also " +
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
if ($DiagnosticOnly) {
    throw "Preflight completed in diagnostic-only mode because one or more required gates were skipped. V2 is not qualified."
}
if (-not $PreflightPassed) {
    throw "Preflight ended without a qualified result."
}

Write-Host ""
Write-Host "STEP9_FULL_TONIGHT_PREFLIGHT_V2: QUALIFIED"
Write-Host "NEXT SESSION DATE: $NextSessionDate"
Write-Host "MARKER: $Marker"
Write-Host "VALIDATION ITERATIONS: $ValidationIterations"
Write-Host "FULL SUITE: PASSED"
Write-Host "RUNTIME MANIFEST: PASSED BEFORE AND AFTER"
Write-Host "REAL DATABASES AND SIDECARS: BYTE-FOR-BYTE UNCHANGED"
Write-Host "SCHEDULER MUST SHOW PRIMARY AND WATCHDOG AS READY."
Write-Host "STEP 9S MANDATORY BENCHMARK CONTROL: TRUE"
Write-Host "STEP 9U MANDATORY CONTROL: FALSE"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
