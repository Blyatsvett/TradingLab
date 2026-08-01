param(
    [switch]$StaticOnly,
    [switch]$SkipTests,
    [switch]$CheckVerifiedPackage,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Project Python was not found: $PythonPath. Run .\setup_regime_trading.ps1 first."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Write-Host "=== $Label ==="
    & $PythonPath -B @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

if (-not $StaticOnly) {
    Invoke-Checked -Label "DEPENDENCY CHECK" -Arguments @(
        "tools\check_dependencies.py"
    )
}

Invoke-Checked -Label "PYTHON COMPILE CHECK" -Arguments @(
    "-m", "compileall", "-q", "RegimeTrading", "tests", "tools"
)

Invoke-Checked -Label "CANONICAL PIPELINE CONTRACT CHECK" -Arguments @(
    "tools\validate_canonical_pipeline.py"
)

$JsonFiles = @(Get-ChildItem -LiteralPath "config" -Filter "*.json" -File -Recurse)
foreach ($JsonFile in $JsonFiles) {
    try {
        $null = Get-Content -LiteralPath $JsonFile.FullName -Raw | ConvertFrom-Json
    }
    catch {
        throw "Invalid JSON: $($JsonFile.FullName): $($_.Exception.Message)"
    }
}
Write-Host "CONFIG JSON CHECK: PASSED ($($JsonFiles.Count) files)"

$PackageRoot = Join-Path $ProjectRoot "Zip bod installation\STEP9_MORNING_V2_VERIFIED_INSTALL_20260730\payload"
$PackageManifest = Join-Path $PackageRoot "package_manifest.json"
if ($CheckVerifiedPackage -and
    (Test-Path -LiteralPath $PackageRoot -PathType Container) -and
    (Test-Path -LiteralPath $PackageManifest -PathType Leaf)) {
    Invoke-Checked -Label "STEP 9 MORNING V2 PACKAGE CHECK" -Arguments @(
        "tools\validate_step9_morning_v2_package.py",
        "--payload-root", $PackageRoot,
        "--manifest", $PackageManifest
    )
}
elseif ($CheckVerifiedPackage) {
    Write-Warning "Verified install payload is not present; package check skipped."
}

if (-not $SkipTests -and -not $StaticOnly) {
    Invoke-Checked -Label "PYTEST SUITE" -Arguments @(
        "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"
    )
}

Write-Host ""
Write-Host "REGIME TRADING PROJECT VALIDATION: PASSED"
Write-Host "ORDERS ENABLED: FALSE"
Write-Host "ROUTER ACTIVE: FALSE"
