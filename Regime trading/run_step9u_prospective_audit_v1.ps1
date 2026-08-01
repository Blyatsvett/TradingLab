param(
    [string]$LedgerDb = "data\step9u_contingency_selector_prospective_shadow_v1.db"
)
$ErrorActionPreference = "Stop"
python -m RegimeTrading.scripts.step9u_prospective_contingency_selector_v1 audit --ledger-db $LedgerDb
exit $LASTEXITCODE
