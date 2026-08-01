# Pre-Step 9S EOD Lifecycle Verification V1

Status: verification-only; no trading or production changes.

## Scope

This package adds only:

- `tools/verify_pre_step9s_eod_lifecycle.py`
- this installation document

It does not include or modify:

- Step 9I or Step 9L engine code
- Step 9Q code or schema
- any SQLite database or ledger
- any CSV export
- any ORB project file
- any router or order code
- any Step 9S implementation

## Verification performed

The verifier uses the historical session `2026-07-27` and:

1. Hashes the real collector/shadow price databases and real Step 9I/Step 9L ledgers.
2. Creates temporary Step 9I V2 and Step 9L V3 ledgers outside the project.
3. Seals reconstructed historical morning batches in those temporary ledgers.
4. Confirms identical morning reruns return the existing rows.
5. Probes the immutable-insert guard with a conflicting duplicate and confirms rejection.
6. Runs EOD evaluation in both temporary ledgers.
7. Confirms EOD reruns are idempotent.
8. Confirms morning rows are unchanged before and after EOD.
9. Compares reconstructed decision and outcome content with the real July 27 sealed ledgers.
10. Builds and validates a temporary Step 9Q workbook from the real sealed ledgers using read-only connections.
11. Re-hashes all protected real files and requires byte-for-byte equality.
12. Deletes temporary ledgers and workbook automatically.

## Protected real files

- `data/intraday_prices.db`
- `data/step9i_shadow_intraday_prices.db`
- `data/step9i_v2_shadow_ledger.db`
- `data/step9l_v3_selected_strategy_shadow_ledger.db`
- `config/step9q_powerbi_schema_v1.json`

## Run

From the project root with `.venv` active:

```powershell
python tools\verify_pre_step9s_eod_lifecycle.py
```

## Expected final output

```text
PRE_STEP9S_EOD_LIFECYCLE_VERIFICATION: PASSED
SESSION_DATE: 2026-07-27
STEP9I_V2: 184 morning rows / 0 eligible / 184 EOD rows / 0 completed trades
STEP9L_V3: 184 morning rows / 32 eligible / 9 active guardrails / 184 EOD rows / 2 primary completed / 2 counterfactual guardrail completed
STEP9L_V3_PRIMARY_RISK_CAPPED_PNL_SEK: -4.663401
STEP9L_V3_COUNTERFACTUAL_GUARDRAIL_PNL_SEK: 4.252440
MORNING_IMMUTABILITY: PASSED (unchanged through EOD; conflicting duplicate rejected)
EOD_IDEMPOTENCY: PASSED (identical reruns returned existing outcomes)
REAL_LEDGER_REPRODUCTION: PASSED (decision/outcome content matches July 27 sealed ledgers)
STEP9Q_REAL_SEALED_READ_ONLY: PASSED (184/184 rows; temporary workbook validated)
PROTECTED_REAL_FILES: BYTE_FOR_BYTE_UNCHANGED
TEMPORARY_LEDGERS_AND_WORKBOOK: DELETED
NO ORDER WAS SENT
```
