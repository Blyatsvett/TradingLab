# Step 9Q-A — Read-only Excel Monitoring Feed

## Install

Extract this ZIP into the root of:

`C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading`

The patch adds new Step 9Q-A files only. It does not replace Step 9I, Step 9L, or production ORB files.

## Verify

From the activated project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_step9q_powerbi_excel_feed.py" -v
```

Expected: 7 tests and `OK`.

## Build a snapshot

Latest available sealed session:

```powershell
.\run_step9q_powerbi_snapshot.ps1
```

Specific session:

```powershell
.\run_step9q_powerbi_snapshot.ps1 -Date "2026-07-27"
```

Require both Step 9I and Step 9L to be present and internally complete:

```powershell
.\run_step9q_powerbi_snapshot.ps1 -Date "2026-07-27" -RequireBothEngines
```

## Output

`data\powerbi\powerbi_live_master.xlsx`

Power BI should connect to these named Excel tables:

- `tblSystemStatus`
- `tblEngineStatus`
- `tblSignalDecisions`
- `tblEngineComparison`
- `tblFeedHealth`

## Safety contract

- SQLite sources are opened with `mode=ro` and `PRAGMA query_only=ON`.
- Existing source ledgers are never written to.
- Workbook publication is atomic.
- A failed validation does not overwrite the previous valid workbook.
- Step 9Q-A exports morning state only.
- It does not calculate intraday trade outcomes or send orders.
