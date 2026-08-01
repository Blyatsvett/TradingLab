# Step 9R V1 zero-eligible morning hotfix

## Problem
A valid sealed V3 morning with `Decisions / eligible: 184/0` produces no eligible
candidate rows. The Step 9R morning selector attempted to read the absent
`model_eligible` column from an empty DataFrame and raised `KeyError`.

## Fix
- Preserves a schema-stable empty prospective candidate frame.
- Uses explicit Boolean row masks that retain columns on empty frames.
- Records the valid morning as a Step 9R batch with:
  - candidate_rows = 0
  - selected_rows = 0
  - confirmatory status inherited from the sealed V3 batch
- Sends no orders and does not change Step 9I or Step 9L.
- Adds a regression test for a zero-eligible prospective day.

## Install
Extract this ZIP into the Regime trading project root and replace the two files.

## Test
```powershell
.\.venv\Scripts\python.exe -m unittest discover `
    -s tests `
    -p "test_step9r*.py" `
    -v
```

Expected: 14 tests, OK.

## Resume today's workflow
Do not rerun Step 9I or Step 9L. Run only:

```powershell
$Date = "2026-07-28"

.\run_step9r_v1_prospective_shadow.ps1 -Date $Date

.\run_step9q_powerbi_snapshot.ps1 `
    -Date $Date `
    -RequireBothEngines
```

Expected Step 9R result:
- Candidate rows: 0
- Selected rows: 0
- No order was sent and V3 was not changed.
