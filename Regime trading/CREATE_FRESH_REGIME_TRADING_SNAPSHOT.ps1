param(
    [string]$ProjectRoot = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = $PSScriptRoot
}

if (-not $OutputDirectory) {
    $OutputDirectory = [Environment]::GetFolderPath("Desktop")
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Project root was not found: $ProjectRoot"
}

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BaseName = "regime_trading_fresh_snapshot_$Timestamp"
$Stage = Join-Path $env:TEMP $BaseName
$ZipPath = Join-Path $OutputDirectory "$BaseName.zip"
$HashPath = Join-Path $OutputDirectory "$BaseName.sha256"

if (Test-Path -LiteralPath $Stage) {
    Remove-Item -LiteralPath $Stage -Recurse -Force
}

New-Item -ItemType Directory -Path $Stage -Force | Out-Null

Write-Host ""
Write-Host "=== CREATING FRESH REGIME TRADING SNAPSHOT ==="
Write-Host "Project root : $ProjectRoot"
Write-Host "Staging      : $Stage"
Write-Host "Output ZIP   : $ZipPath"
Write-Host ""

# Copy current code, configs, tests, data, ledgers, outputs and Power BI files.
# Exclude only the virtual environment, version-control metadata and caches.
$RoboArgs = @(
    $ProjectRoot,
    $Stage,
    "/E",
    "/R:1",
    "/W:1",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP",
    "/XD",
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "/XF",
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.lock",
    "~*"
)

& robocopy @RoboArgs | Out-Host
$RoboCode = $LASTEXITCODE

# Robocopy exit codes 0 through 7 are success states.
if ($RoboCode -gt 7) {
    throw "Robocopy failed with exit code $RoboCode"
}

$Manifest = @"
REGIME TRADING FRESH SNAPSHOT
=============================
Created        : $(Get-Date -Format "yyyy-MM-dd HH:mm:ss K")
Source root    : $ProjectRoot
Python venv    : excluded
Git metadata   : excluded
Python caches  : excluded
Included       : source, tests, configs, PowerShell launchers, databases, ledgers, outputs and Power BI files
Purpose        : migrate the exact current local project state into a new ChatGPT chat
"@

$Manifest | Set-Content -LiteralPath (Join-Path $Stage "FRESH_SNAPSHOT_MANIFEST.txt") -Encoding UTF8

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $Stage,
    $ZipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)

$Hash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256
"$($Hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($ZipPath))" |
    Set-Content -LiteralPath $HashPath -Encoding ASCII

Remove-Item -LiteralPath $Stage -Recurse -Force

Write-Host ""
Write-Host "=== SNAPSHOT COMPLETE ==="
Write-Host "ZIP    : $ZipPath"
Write-Host "SHA256 : $($Hash.Hash.ToLowerInvariant())"
Write-Host "Hash file: $HashPath"
Write-Host ""
Write-Host "Upload the ZIP together with the new-chat migration pack."
