param(
    [string]$LedgerDb = "data\step9t_regime_transition_archetype_prospective_v1.db"
)

$ErrorActionPreference = "Stop"

python -m RegimeTrading.scripts.step9t_prospective_regime_transition_archetype_v1 `
    audit `
    --ledger-db $LedgerDb

exit $LASTEXITCODE
