param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowLateReconstruction,
    [string]$LedgerDb = "data\step9t_regime_transition_archetype_prospective_v1.db"
)

$ErrorActionPreference = "Stop"

$Arguments = @(
    "-m",
    "RegimeTrading.scripts.step9t_prospective_regime_transition_archetype_v1",
    "morning",
    "--ledger-db",
    $LedgerDb
)

if ($Date) {
    $Arguments += @("--date", $Date)
}
if ($AsOf) {
    $Arguments += @("--as-of", $AsOf)
}
if ($AllowLateReconstruction) {
    $Arguments += "--allow-late-reconstruction"
}

python @Arguments
exit $LASTEXITCODE
