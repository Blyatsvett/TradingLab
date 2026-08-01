Set-StrictMode -Version Latest

function Get-Step9MorningV2ExitField {
    param(
        [AllowNull()]
        [object]$InputObject,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowNull()]
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

function Resolve-Step9MorningV2ExitCode {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [object]$ProcessExitCode,
        [Parameter(Mandatory = $true)]
        [bool]$ProcessHasExited,
        [AllowNull()]
        [object]$SemanticPayload = $null,
        [string]$ExpectedSemanticStatus = "",
        [AllowNull()]
        [string]$StandardErrorText = ""
    )

    if (-not $ProcessHasExited) {
        throw "Cannot resolve an exit code for a process that has not exited."
    }

    $RawText = if ($null -eq $ProcessExitCode) {
        ""
    }
    else {
        [string]$ProcessExitCode
    }

    if (-not [string]::IsNullOrWhiteSpace($RawText)) {
        $ParsedExitCode = 0
        if (-not [int]::TryParse($RawText, [ref]$ParsedExitCode)) {
            throw "Process exit code is not an integer: '$RawText'."
        }
        return [PSCustomObject]@{
            exit_code = $ParsedExitCode
            source = "PROCESS_EXIT_CODE"
            semantic_status = [string](Get-Step9MorningV2ExitField -InputObject $SemanticPayload -Name "status" -Default "")
            stderr_present = -not [string]::IsNullOrWhiteSpace($StandardErrorText)
        }
    }

    if ([string]::IsNullOrWhiteSpace($ExpectedSemanticStatus)) {
        throw "Process exited but its exit code was blank and no semantic success contract was supplied."
    }
    if ($null -eq $SemanticPayload) {
        throw "Process exited with a blank exit code and no semantic result payload was available."
    }

    $ActualStatus = [string](Get-Step9MorningV2ExitField -InputObject $SemanticPayload -Name "status" -Default "")
    if ($ActualStatus -ne $ExpectedSemanticStatus) {
        throw (
            "Process exited with a blank exit code and semantic status '$ActualStatus' " +
            "did not match '$ExpectedSemanticStatus'."
        )
    }
    if ([bool](Get-Step9MorningV2ExitField -InputObject $SemanticPayload -Name "router_active" -Default $true)) {
        throw "Blank exit code cannot be normalized because router_active is not false."
    }
    if ([bool](Get-Step9MorningV2ExitField -InputObject $SemanticPayload -Name "orders_enabled" -Default $true)) {
        throw "Blank exit code cannot be normalized because orders_enabled is not false."
    }

    return [PSCustomObject]@{
        exit_code = 0
        source = "SEMANTIC_SUCCESS_NORMALIZATION"
        semantic_status = $ActualStatus
        stderr_present = -not [string]::IsNullOrWhiteSpace($StandardErrorText)
    }
}
