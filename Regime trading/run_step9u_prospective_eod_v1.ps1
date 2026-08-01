param(
    [string]$Date = "",
    [string]$AsOf = "",
    [switch]$AllowEarlyEvaluation,
    [string]$Step9TLedgerDb = "data\step9t_regime_transition_archetype_prospective_v1.db",
    [string]$LedgerDb = "data\step9u_contingency_selector_prospective_shadow_v1.db"
)
$ErrorActionPreference = "Stop"
$Arguments = @("-m", "RegimeTrading.scripts.step9u_prospective_contingency_selector_v1", "eod", "--step9t-ledger-db", $Step9TLedgerDb, "--ledger-db", $LedgerDb)
if ($Date) { $Arguments += @("--date", $Date) }
if ($AsOf) { $Arguments += @("--as-of", $AsOf) }
if ($AllowEarlyEvaluation) { $Arguments += "--allow-early-evaluation" }
python @Arguments
exit $LASTEXITCODE
