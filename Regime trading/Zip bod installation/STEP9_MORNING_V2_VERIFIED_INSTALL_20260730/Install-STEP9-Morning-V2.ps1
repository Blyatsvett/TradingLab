param(
    [string]$ProjectRoot = "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading",
    [string]$PythonExe = "",
    [ValidateRange(0, 100)]
    [int]$FaultInjectionFailAfterFileCount = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedPackageManifestHash = "1dd11e4b4557478ab3abccdfe1f074a48dfe16d4fa347251bd1142fb8bf2cb54"
$BundleRoot = $PSScriptRoot
$PayloadRoot = Join-Path $BundleRoot "payload"
$PackageManifestPath = Join-Path $PayloadRoot "package_manifest.json"
$RuntimeManifestPath = Join-Path $PayloadRoot "config\step9_morning_v2_runtime_manifest.json"
$Validator = Join-Path $PayloadRoot "tools\validate_step9_morning_v2_package.py"
$RunId = "{0}_{1}" -f (Get-Date -Format "yyyyMMdd_HHmmss"), ([guid]::NewGuid().ToString("N"))
$BackupRoot = Join-Path $env:USERPROFILE "Documents\STEP9_MORNING_V2_BACKUPS\$RunId"
$ValidationRoot = Join-Path ([IO.Path]::GetTempPath()) "step9_v2_install_$RunId"
$ChangedTargets = New-Object System.Collections.Generic.List[string]
$ExistingTargets = New-Object System.Collections.Generic.HashSet[string]
$Committed = $false
$ProtectedBefore = $null
$ReceiptPath = ""
$ReceiptTemporaryPath = ""

function Get-NormalizedFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath($Path).TrimEnd("\")
}

function Assert-NoReparsePointInExistingAncestors {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $FullPath = [IO.Path]::GetFullPath($Path)
    $DriveRoot = [IO.Path]::GetPathRoot($FullPath)
    if ([string]::IsNullOrWhiteSpace($DriveRoot)) {
        throw "$Label has no filesystem root: $FullPath"
    }

    # A normal drive root is not treated as an installable ancestor. Check each
    # existing component below it and stop at the first component not yet made.
    $Current = $DriveRoot
    $Remainder = $FullPath.Substring($DriveRoot.Length)
    $Parts = @(
        $Remainder.Split(
            @([char]92, [char]47),
            [StringSplitOptions]::RemoveEmptyEntries
        )
    )
    foreach ($Part in $Parts) {
        $Current = Join-Path $Current $Part
        if (-not (Test-Path -LiteralPath $Current)) {
            break
        }
        $Item = Get-Item -LiteralPath $Current -Force -ErrorAction Stop
        if (
            ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "$Label traverses a junction or symbolic link: $Current"
        }
    }
}

function Get-SafeDestination {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Relative
    )
    if (
        [IO.Path]::IsPathRooted($Relative) -or
        $Relative.Split(@("\", "/"), [StringSplitOptions]::RemoveEmptyEntries) -contains ".."
    ) {
        throw "Unsafe payload path: $Relative"
    }
    $RootFull = Get-NormalizedFullPath -Path $Root
    $Candidate = [IO.Path]::GetFullPath((Join-Path $RootFull $Relative))
    if (
        $Candidate -ne $RootFull -and
        -not $Candidate.StartsWith($RootFull + "\", [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Payload path escapes project root: $Relative"
    }
    Assert-NoReparsePointInExistingAncestors `
        -Path $Candidate `
        -Label "Resolved package path"
    return $Candidate
}

function Get-ProtectedHashes {
    param([Parameter(Mandatory = $true)][string]$Root)
    $Result = [ordered]@{}
    $DataRoot = Join-Path $Root "data"
    if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
        return $Result
    }
    Get-ChildItem -LiteralPath $DataRoot -Recurse -File -ErrorAction Stop |
        Where-Object {
            $_.Name -match "\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$"
        } |
        Sort-Object FullName |
        ForEach-Object {
            $Relative = $_.FullName.Substring($Root.Length + 1).Replace("\", "/")
            $Result[$Relative] = (
                Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
            ).Hash.ToLower()
        }
    return $Result
}

function Assert-HashesEqual {
    param(
        [Parameter(Mandatory = $true)][object]$Before,
        [Parameter(Mandatory = $true)][object]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $BeforeKeys = @($Before.Keys | Sort-Object)
    $AfterKeys = @($After.Keys | Sort-Object)
    if (($BeforeKeys -join "`n") -ne ($AfterKeys -join "`n")) {
        throw "$Label file inventory changed."
    }
    foreach ($Key in $BeforeKeys) {
        if ([string]$Before[$Key] -ne [string]$After[$Key]) {
            throw "$Label hash changed: $Key"
        }
    }
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    $Output = @()
    $ExitCode = -1
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $PreviousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $Output = @(& $PythonExe @Arguments 2>&1)
            $ExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousPreference
        }
    }
    finally {
        Pop-Location
    }
    foreach ($Line in @($Output)) {
        Write-Host ([string]$Line)
    }
    if ($ExitCode -ne 0) {
        throw "$Label failed with exit code $ExitCode."
    }
}

function Restore-Installation {
    param(
        [Parameter(Mandatory = $true)][object[]]$Entries,
        [Parameter(Mandatory = $true)][string]$Root
    )
    foreach ($Entry in @($Entries | Sort-Object relative_path -Descending)) {
        $Relative = [string]$Entry.relative_path
        $Target = Get-SafeDestination -Root $Root -Relative $Relative
        $Backup = Join-Path $BackupRoot $Relative
        if ($ExistingTargets.Contains($Relative)) {
            if (-not (Test-Path -LiteralPath $Backup -PathType Leaf)) {
                throw "Rollback backup is missing: $Backup"
            }
            $Parent = Split-Path -Parent $Target
            New-Item -ItemType Directory -Path $Parent -Force | Out-Null
            Copy-Item -LiteralPath $Backup -Destination $Target -Force
        }
        elseif (Test-Path -LiteralPath $Target -PathType Leaf) {
            Remove-Item -LiteralPath $Target -Force
        }
    }
}

try {
    $ProjectRoot = Get-NormalizedFullPath -Path $ProjectRoot
    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
        throw "Project root is missing: $ProjectRoot"
    }
    Assert-NoReparsePointInExistingAncestors `
        -Path $ProjectRoot `
        -Label "Project root"
    Assert-NoReparsePointInExistingAncestors `
        -Path $BundleRoot `
        -Label "Installation bundle"
    Assert-NoReparsePointInExistingAncestors `
        -Path $PayloadRoot `
        -Label "Installation payload"
    Assert-NoReparsePointInExistingAncestors `
        -Path $BackupRoot `
        -Label "Rollback backup"
    Assert-NoReparsePointInExistingAncestors `
        -Path $ValidationRoot `
        -Label "Validation workspace"
    if ([string]::IsNullOrWhiteSpace($PythonExe)) {
        $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    }
    $PythonExe = [IO.Path]::GetFullPath($PythonExe)
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Project Python is missing: $PythonExe"
    }
    Assert-NoReparsePointInExistingAncestors `
        -Path $PythonExe `
        -Label "Project Python"
    if (-not (Test-Path -LiteralPath $PackageManifestPath -PathType Leaf)) {
        throw "Package manifest is missing: $PackageManifestPath"
    }
    if (-not (Test-Path -LiteralPath $RuntimeManifestPath -PathType Leaf)) {
        throw "Runtime compatibility manifest is missing: $RuntimeManifestPath"
    }
    if (-not (Test-Path -LiteralPath $Validator -PathType Leaf)) {
        throw "Package validator is missing: $Validator"
    }

    $ManifestHash = (
        Get-FileHash -LiteralPath $PackageManifestPath -Algorithm SHA256
    ).Hash.ToLower()
    if ($ManifestHash -ne $ExpectedPackageManifestHash) {
        throw "Package manifest hash mismatch. Do not install."
    }
    $PackageManifest = Get-Content -LiteralPath $PackageManifestPath -Raw |
        ConvertFrom-Json
    $Entries = @(
        $PackageManifest.files.psobject.Properties |
            Sort-Object Name |
            ForEach-Object {
                [PSCustomObject]@{
                    relative_path = [string]$_.Name
                    sha256 = ([string]$_.Value).ToLower()
                }
            }
    )
    if ($Entries.Count -lt 12) {
        throw "Package manifest is unexpectedly small."
    }
    $ValidatorRelative = "tools/validate_step9_morning_v2_package.py"
    $ValidatorEntries = @(
        $Entries | Where-Object {
            ([string]$_.relative_path).Replace("\", "/") -eq $ValidatorRelative
        }
    )
    if ($ValidatorEntries.Count -ne 1) {
        throw "Pinned package manifest must contain exactly one validator entry."
    }
    $ValidatorHash = (
        Get-FileHash -LiteralPath $Validator -Algorithm SHA256
    ).Hash.ToLower()
    if ($ValidatorHash -ne [string]$ValidatorEntries[0].sha256) {
        throw "Package validator hash mismatch. It will not be executed."
    }
    Write-Host "PINNED VALIDATOR HASH: $ValidatorHash"

    Write-Host ""
    Write-Host "=== VERIFY SELF-CONTAINED PAYLOAD ==="
    New-Item -ItemType Directory -Path $ValidationRoot -Force | Out-Null
    $ValidationJson = Join-Path $ValidationRoot "package_validation.json"
    Invoke-Python -Label "Payload validation" -WorkingDirectory $PayloadRoot -Arguments @(
        "-B", $Validator,
        "--payload-root", $PayloadRoot,
        "--manifest", $PackageManifestPath,
        "--json-out", $ValidationJson
    )

    $PowerShellFiles = @(
        Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File -Filter "*.ps1"
    )
    foreach ($File in $PowerShellFiles) {
        $Raw = [IO.File]::ReadAllBytes($File.FullName)
        if (@($Raw | Where-Object { $_ -gt 127 }).Count -gt 0) {
            throw "PowerShell file is not ASCII-safe: $($File.FullName)"
        }
        $Tokens = $null
        $ParseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile(
            $File.FullName,
            [ref]$Tokens,
            [ref]$ParseErrors
        ) | Out-Null
        if (@($ParseErrors).Count -gt 0) {
            $Messages = @($ParseErrors | ForEach-Object { $_.Message }) -join " | "
            throw "PowerShell parser failed for $($File.Name): $Messages"
        }
        Write-Host "PARSED: $($File.Name)"
    }

    Write-Host ""
    Write-Host "=== VERIFY AUDITED PROJECT RUNTIME ==="
    $RuntimeManifest = Get-Content -LiteralPath $RuntimeManifestPath -Raw |
        ConvertFrom-Json
    $RuntimeEntries = @($RuntimeManifest.files.psobject.Properties)
    if ($RuntimeEntries.Count -lt 35) {
        throw "Runtime dependency manifest is unexpectedly small."
    }
    $PayloadPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Entry in $Entries) {
        [void]$PayloadPaths.Add(
            ([string]$Entry.relative_path).Replace("\", "/")
        )
    }
    foreach ($Property in $RuntimeEntries) {
        $Relative = ([string]$Property.Name).Replace("\", "/")
        if ($PayloadPaths.Contains($Relative)) {
            $PayloadFile = Get-SafeDestination -Root $PayloadRoot `
                -Relative $Relative
            if (-not (Test-Path -LiteralPath $PayloadFile -PathType Leaf)) {
                throw "Package-owned runtime file is missing: $Relative"
            }
            $PayloadHash = (
                Get-FileHash -LiteralPath $PayloadFile -Algorithm SHA256
            ).Hash.ToLower()
            if ($PayloadHash -ne ([string]$Property.Value).ToLower()) {
                throw "Package-owned runtime hash differs from its closure manifest: $Relative"
            }
            Write-Host "PAYLOAD MATCH: $Relative"
            continue
        }
        $Path = Get-SafeDestination -Root $ProjectRoot -Relative $Relative
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Required audited runtime file is missing: $Relative"
        }
        $Actual = (
            Get-FileHash -LiteralPath $Path -Algorithm SHA256
        ).Hash.ToLower()
        if ($Actual -ne ([string]$Property.Value).ToLower()) {
            throw "Current project differs from the audited source: $Relative"
        }
        Write-Host "MATCH: $Relative"
    }

    $Now = Get-Date
    if (
        $Now.DayOfWeek -notin @(
            [DayOfWeek]::Saturday,
            [DayOfWeek]::Sunday
        ) -and
        $Now.TimeOfDay -ge ([TimeSpan]::Parse("09:35:00")) -and
        $Now.TimeOfDay -le ([TimeSpan]::Parse("10:10:00"))
    ) {
        throw "Installation is blocked during the live morning safety window."
    }

    Write-Host ""
    Write-Host "=== RUN ISOLATED FOCUSED TESTS BEFORE INSTALL ==="
    $PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    $env:PYTHONDONTWRITEBYTECODE = "1"
    try {
        $TestArguments = @(
            "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            (Join-Path $PayloadRoot "tests\test_step9_morning_v2_support.py"),
            (Join-Path $PayloadRoot "tests\test_step9_morning_v2_install_contract.py")
        )
        $HardeningTest = Join-Path $PayloadRoot "tests\test_step9_morning_v2_hardening.py"
        if (Test-Path -LiteralPath $HardeningTest -PathType Leaf) {
            $TestArguments += $HardeningTest
        }
        Invoke-Python -Label "Focused Step 9 Morning V2 tests" `
            -WorkingDirectory $PayloadRoot -Arguments $TestArguments
    }
    finally {
        $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode
    }

    $ProtectedBefore = Get-ProtectedHashes -Root $ProjectRoot
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

    Write-Host ""
    Write-Host "=== CREATE COMPLETE ROLLBACK BACKUP ==="
    foreach ($Entry in $Entries) {
        $Relative = [string]$Entry.relative_path
        $Target = Get-SafeDestination -Root $ProjectRoot -Relative $Relative
        if (Test-Path -LiteralPath $Target -PathType Leaf) {
            [void]$ExistingTargets.Add($Relative)
            $Backup = Join-Path $BackupRoot $Relative
            Assert-NoReparsePointInExistingAncestors `
                -Path $Backup `
                -Label "Rollback backup target"
            New-Item -ItemType Directory -Path (Split-Path -Parent $Backup) -Force |
                Out-Null
            Copy-Item -LiteralPath $Target -Destination $Backup -Force
        }
    }

    Write-Host ""
    Write-Host "=== TRANSACTIONAL INSTALL ==="
    $InstalledThisRun = 0
    foreach ($Entry in $Entries) {
        $Relative = [string]$Entry.relative_path
        $Source = Get-SafeDestination -Root $PayloadRoot -Relative $Relative
        $Target = Get-SafeDestination -Root $ProjectRoot -Relative $Relative
        $TargetParent = Split-Path -Parent $Target
        New-Item -ItemType Directory -Path $TargetParent -Force | Out-Null
        $TemporaryTarget = "$Target.step9v2.$RunId.tmp"
        $ReplacementBackup = "$Target.step9v2.$RunId.replaced"
        $ChangedTargets.Add($Relative)
        try {
            Copy-Item -LiteralPath $Source -Destination $TemporaryTarget -Force
            if (Test-Path -LiteralPath $Target -PathType Leaf) {
                [IO.File]::Replace(
                    $TemporaryTarget,
                    $Target,
                    $ReplacementBackup
                )
            }
            else {
                Move-Item -LiteralPath $TemporaryTarget -Destination $Target
            }
        }
        finally {
            if (Test-Path -LiteralPath $TemporaryTarget -PathType Leaf) {
                Remove-Item -LiteralPath $TemporaryTarget -Force
            }
            if (Test-Path -LiteralPath $ReplacementBackup -PathType Leaf) {
                Remove-Item -LiteralPath $ReplacementBackup -Force
            }
        }
        $InstalledThisRun += 1
        $Actual = (
            Get-FileHash -LiteralPath $Target -Algorithm SHA256
        ).Hash.ToLower()
        if ($Actual -ne [string]$Entry.sha256) {
            throw "Installed file hash mismatch: $Relative"
        }
        Write-Host "INSTALLED: $Relative"
        if (
            $FaultInjectionFailAfterFileCount -gt 0 -and
            $InstalledThisRun -ge $FaultInjectionFailAfterFileCount
        ) {
            if ($env:STEP9_V2_INSTALL_TEST_MODE -ne "1") {
                throw (
                    "Fault injection is restricted to an isolated test environment. " +
                    "STEP9_V2_INSTALL_TEST_MODE is not enabled."
                )
            }
            throw "TEST_ONLY_FAULT_INJECTION_AFTER_$InstalledThisRun"
        }
    }

    $RuntimeCheckJson = Join-Path $ValidationRoot "runtime_check.json"
    $InstalledSupport = Join-Path $ProjectRoot "tools\step9_morning_v2_support.py"
    $InstalledRuntimeManifest = Join-Path $ProjectRoot (
        "config\step9_morning_v2_runtime_manifest.json"
    )
    Invoke-Python -Label "Installed runtime compatibility check" `
        -WorkingDirectory $ProjectRoot -Arguments @(
            "-B", $InstalledSupport,
            "runtime-manifest",
            "--manifest", $InstalledRuntimeManifest,
            "--root", $ProjectRoot,
            "--json-out", $RuntimeCheckJson
        )

    $ProtectedAfter = Get-ProtectedHashes -Root $ProjectRoot
    Assert-HashesEqual -Before $ProtectedBefore -After $ProtectedAfter `
        -Label "Protected SQLite files"

    $ReceiptDir = Get-SafeDestination -Root $ProjectRoot -Relative "logs"
    New-Item -ItemType Directory -Path $ReceiptDir -Force | Out-Null
    $ReceiptPath = Join-Path $ReceiptDir "step9_morning_v2_install_$RunId.json"
    $ReceiptTemporaryPath = "$ReceiptPath.tmp"
    [ordered]@{
        status = "STEP9_FULL_LIVE_MORNING_ORCHESTRATOR_V2_INSTALLED"
        installed_at = (Get-Date).ToString("o")
        package_id = [string]$PackageManifest.package_id
        package_manifest_sha256 = $ManifestHash
        files_installed = $Entries.Count
        runtime_dependencies_verified = $RuntimeEntries.Count
        rollback_backup = $BackupRoot
        protected_sqlite_files_unchanged = $true
        scheduled_tasks_registered = $false
        production_orb_touched = $false
        router_active = $false
        orders_enabled = $false
    } | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $ReceiptTemporaryPath -Encoding UTF8
    Move-Item -LiteralPath $ReceiptTemporaryPath -Destination $ReceiptPath
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
        throw "Installation receipt was not committed."
    }
    $Committed = $true

    Write-Host ""
    Write-Host "STEP9_FULL_LIVE_MORNING_ORCHESTRATOR_V2: INSTALLED"
    Write-Host "PACKAGE: $($PackageManifest.package_id)"
    Write-Host "FILES INSTALLED: $($Entries.Count)"
    Write-Host "RUNTIME DEPENDENCIES VERIFIED: $($RuntimeEntries.Count)"
    Write-Host "ROLLBACK BACKUP: $BackupRoot"
    Write-Host "INSTALL RECEIPT: $ReceiptPath"
    Write-Host "SCHEDULED TASKS: NOT REGISTERED"
    Write-Host "PROTECTED SQLITE FILES: BYTE-FOR-BYTE UNCHANGED"
    Write-Host "PRODUCTION ORB: UNTOUCHED"
    Write-Host "ROUTER ACTIVE: FALSE"
    Write-Host "NO ORDER WAS SENT"
}
catch {
    $InstallError = $_
    if (
        -not $Committed -and
        -not [string]::IsNullOrWhiteSpace($ReceiptTemporaryPath) -and
        (Test-Path -LiteralPath $ReceiptTemporaryPath -PathType Leaf)
    ) {
        Remove-Item -LiteralPath $ReceiptTemporaryPath -Force `
            -ErrorAction SilentlyContinue
    }
    if (
        -not $Committed -and
        -not [string]::IsNullOrWhiteSpace($ReceiptPath) -and
        (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)
    ) {
        Remove-Item -LiteralPath $ReceiptPath -Force `
            -ErrorAction SilentlyContinue
    }
    if (-not $Committed -and $ChangedTargets.Count -gt 0) {
        try {
            Restore-Installation -Entries $Entries -Root $ProjectRoot
            Write-Warning "Installation failed; every changed target was rolled back."
        }
        catch {
            Write-Warning "ROLLBACK ERROR: $($_.Exception.Message)"
        }
    }
    if ($null -ne $ProtectedBefore) {
        try {
            $ProtectedOnFailure = Get-ProtectedHashes -Root $ProjectRoot
            Assert-HashesEqual -Before $ProtectedBefore -After $ProtectedOnFailure `
                -Label "Protected SQLite files after failed installation"
        }
        catch {
            Write-Warning "PROTECTED SQLITE VERIFICATION ERROR: $($_.Exception.Message)"
        }
    }
    throw $InstallError
}
finally {
    if (Test-Path -LiteralPath $ValidationRoot -PathType Container) {
        Remove-Item -LiteralPath $ValidationRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
