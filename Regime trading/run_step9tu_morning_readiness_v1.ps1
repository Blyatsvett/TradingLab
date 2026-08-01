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
    throw "Morning readiness may only run for today's date. Requested=$Date, today=$((Get-Date).ToString('yyyy-MM-dd'))."
}

$Now = Get-Date
$Earliest = Get-Date -Hour 9 -Minute 45 -Second 0
$Latest = Get-Date -Hour 9 -Minute 47 -Second 50
if ($Now -lt $Earliest) {
    throw "Run morning readiness at or after 09:45:00 Stockholm time. Current time: $($Now.ToString('HH:mm:ss'))."
}
if ($Now -gt $Latest) {
    throw "Readiness window has passed. Use the live wrapper immediately if it is still before 09:49:00. Current time: $($Now.ToString('HH:mm:ss'))."
}

$Offset = [TimeZoneInfo]::Local.GetUtcOffset($Now)
if ($Offset.TotalHours -ne 2) {
    throw "Expected Stockholm summer-time offset +02:00; current local offset is $Offset."
}

try {
    $Processor = Get-CimInstance Win32_Processor | Select-Object -First 1 CurrentClockSpeed, MaxClockSpeed
    Write-Host "CPU clock: $($Processor.CurrentClockSpeed) / $($Processor.MaxClockSpeed) MHz"
    if ([int]$Processor.CurrentClockSpeed -lt 600) {
        Write-Warning "CPU appears severely throttled below 600 MHz. Because this Dell has slowed down while charging, unplug the charger before the live window if the slowdown is active."
    }
} catch {
    Write-Warning "Could not read CPU clock: $($_.Exception.Message)"
}

$Preview = Join-Path $Logs ("step9tu_readiness_{0}_{1}.json" -f $Date.Replace('-', ''), (Get-Date -Format "HHmmss"))
$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $ReadinessOutput = @(& $Python "tools/check_step9tu_morning_readiness_v1.py" readiness --date $Date --json-out $Preview 2>&1)
    $ReadinessExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
@($ReadinessOutput) | ForEach-Object { Write-Host ([string]$_) }
if ($ReadinessExitCode -ne 0) {
    throw "Step 9T -> Step 9U read-only morning readiness failed with exit code $ReadinessExitCode. Repair only the reported prerequisite."
}

Write-Host ""
Write-Host "STEP9TU_MORNING_READINESS_V1: PASSED"
Write-Host "Preview: $Preview"
Write-Host "No prospective ledger was written."
Write-Host "Launch .\run_step9tu_live_morning_v1.ps1 at 09:47:45."
Write-Host "MANDATORY CONTROL ACTIVE: FALSE"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"

