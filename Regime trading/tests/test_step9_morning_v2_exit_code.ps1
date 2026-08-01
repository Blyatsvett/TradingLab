param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
. (Join-Path $Root "tools\step9_morning_v2_exit_code.ps1")

function Assert-Equal {
    param([object]$Expected, [object]$Actual, [string]$Label)
    if ($Expected -ne $Actual) {
        throw "$Label expected '$Expected' but received '$Actual'."
    }
}

function Assert-Throws {
    param([scriptblock]$Action, [string]$Pattern, [string]$Label)
    $Thrown = $false
    try {
        & $Action
    }
    catch {
        $Thrown = $true
        if ($_.Exception.Message -notmatch $Pattern) {
            throw "$Label threw an unexpected message: $($_.Exception.Message)"
        }
    }
    if (-not $Thrown) {
        throw "$Label did not throw."
    }
}

$Passed = [PSCustomObject]@{
    status = "STEP9_MORNING_V2_RUNTIME_COMPATIBILITY_PASSED"
    router_active = $false
    orders_enabled = $false
}

$Result = Resolve-Step9MorningV2ExitCode -ProcessExitCode 0 -ProcessHasExited $true
Assert-Equal 0 $Result.exit_code "native zero"
Assert-Equal "PROCESS_EXIT_CODE" $Result.source "native zero source"

$Result = Resolve-Step9MorningV2ExitCode -ProcessExitCode 9 -ProcessHasExited $true -SemanticPayload $Passed -ExpectedSemanticStatus $Passed.status
Assert-Equal 9 $Result.exit_code "actual nonzero"
Assert-Equal "PROCESS_EXIT_CODE" $Result.source "actual nonzero source"

$global:LASTEXITCODE = 73
& { Write-Output "PowerShell success without native exit-code mutation" } | Out-Null
Assert-Equal 73 $global:LASTEXITCODE "stale LASTEXITCODE precondition"
$Result = Resolve-Step9MorningV2ExitCode -ProcessExitCode $null -ProcessHasExited $true -SemanticPayload $Passed -ExpectedSemanticStatus $Passed.status
Assert-Equal 0 $Result.exit_code "blank exit semantic normalization"
Assert-Equal "SEMANTIC_SUCCESS_NORMALIZATION" $Result.source "blank exit source"

$Result = Resolve-Step9MorningV2ExitCode -ProcessExitCode "" -ProcessHasExited $true -SemanticPayload $Passed -ExpectedSemanticStatus $Passed.status -StandardErrorText "warning only"
Assert-Equal 0 $Result.exit_code "stderr warning does not override semantic success"
Assert-Equal $true $Result.stderr_present "stderr warning recorded"

Assert-Throws -Label "blank without semantic proof" -Pattern "no semantic success contract" -Action {
    Resolve-Step9MorningV2ExitCode -ProcessExitCode $null -ProcessHasExited $true | Out-Null
}

$Failed = [PSCustomObject]@{
    status = "FAILED"
    router_active = $false
    orders_enabled = $false
}
Assert-Throws -Label "failed semantic status" -Pattern "did not match" -Action {
    Resolve-Step9MorningV2ExitCode -ProcessExitCode $null -ProcessHasExited $true -SemanticPayload $Failed -ExpectedSemanticStatus $Passed.status | Out-Null
}

$Unsafe = [PSCustomObject]@{
    status = $Passed.status
    router_active = $true
    orders_enabled = $false
}
Assert-Throws -Label "unsafe router flag" -Pattern "router_active" -Action {
    Resolve-Step9MorningV2ExitCode -ProcessExitCode $null -ProcessHasExited $true -SemanticPayload $Unsafe -ExpectedSemanticStatus $Passed.status | Out-Null
}

Assert-Throws -Label "process still running" -Pattern "has not exited" -Action {
    Resolve-Step9MorningV2ExitCode -ProcessExitCode 0 -ProcessHasExited $false | Out-Null
}

Write-Host "STEP9_MORNING_V2_EXIT_CODE_TESTS_PASSED"
Write-Host "ROUTER ACTIVE: FALSE"
Write-Host "NO ORDER WAS SENT"
