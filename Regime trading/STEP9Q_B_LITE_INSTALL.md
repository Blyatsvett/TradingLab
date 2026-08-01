# Step 9Q-B Lite — Read-only intraday trade monitor for Power BI

## Purpose

Step 9Q-B Lite extends the existing Step 9Q-A workbook with a read-only intraday view of the frozen Step 9L V3 morning decisions.

It adds three named Excel tables:

- `tblLiveTradeStatus`
- `tblTradeHistory`
- `tblAccountSnapshot`

The existing five Step 9Q-A tables remain unchanged:

- `tblSystemStatus`
- `tblEngineStatus`
- `tblSignalDecisions`
- `tblEngineComparison`
- `tblFeedHealth`

## Safety contract

Step 9Q-B Lite:

- reads the Step 9L V3 ledger with SQLite `mode=ro` and `PRAGMA query_only=ON`;
- reads the shared five-minute price database with SQLite `mode=ro`;
- uses only completed start-labelled five-minute bars;
- replays the exact selected Step 9L V3 contract mechanics;
- never changes the frozen morning decisions;
- never writes to Step 9I or Step 9L ledgers;
- never sends an order;
- never changes production ORB logic or paper trading;
- excludes guardrails from primary trade P&L and equity;
- publishes the Excel workbook atomically.

Intraday statuses and P&L are provisional until the normal Step 9L EOD evaluator seals authoritative outcomes.

## Install

1. Close `powerbi_live_master.xlsx` in Excel.
2. Back up the project folder.
3. Extract the patch ZIP directly into:

   `C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading`

4. Allow replacement of the included Step 9Q files. No Step 9I, Step 9L, or ORB file is replaced.

If Windows blocks the new PowerShell file:

```powershell
Unblock-File .\run_step9q_powerbi_snapshot.ps1
```

## Tests

Run the focused Step 9Q suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover `
    -s tests `
    -p "test_step9q*.py" `
    -v
```

Expected result:

```text
Ran 13 tests
OK
```

Run the frozen Step 9L compatibility suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover `
    -s tests `
    -p "test_step9l*.py" `
    -v
```

Expected result:

```text
Ran 31 tests
OK
```

## Build or refresh the monitoring workbook

During the market session:

```powershell
.\collect_step9i_v2_shadow_data.ps1 -Days 5

.\run_step9q_powerbi_snapshot.ps1 `
    -RequireBothEngines
```

For a specific sealed session:

```powershell
.\run_step9q_powerbi_snapshot.ps1 `
    -Date "2026-07-27" `
    -RequireBothEngines
```

Then use **Home → Refresh** in Power BI Desktop.

Do not rerun the morning routers during the day. Step 9Q-B reads the already sealed decisions and updates only the reporting workbook.

## Status meanings

`tblLiveTradeStatus[TradeStatus]` can contain:

- `WAITING_FOR_ENTRY` — selected primary setup whose trigger window remains open;
- `OPEN` — a theoretical shadow trade has triggered and neither stop nor target has been reached on completed bars;
- `CLOSED_PROVISIONAL` — stop, target, or time exit has occurred but EOD is not yet authoritative;
- `NO_TRIGGER` — the entry window closed without a trigger;
- `ELIGIBLE_NOT_SELECTED` — morning eligible but outside the frozen maximum candidate rank;
- `INVALID_SETUP` or another explicit invalid/ambiguous state;
- `ELIGIBLE_NO_CANDIDATE` — morning eligibility existed but the exact execution builder did not produce a candidate.

## Equity fields

`tblAccountSnapshot` contains two equity views:

- `CurrentEquitySEK` — operational shadow equity using all primary shadow trades, including late reconstructions and provisional intraday marks;
- `ConfirmatoryEquitySEK` — clean prospective equity excluding late reconstructions and all guardrails.

The operational value is suitable for the simple live dashboard. The confirmatory value is the research evidence metric.

## Power BI additions

In the existing PBIX, select **Get data → Excel workbook**, select the same `powerbi_live_master.xlsx`, and add only:

- `tblLiveTradeStatus`
- `tblTradeHistory`
- `tblAccountSnapshot`

The previously loaded five tables remain connected.

## Suggested one-page dashboard

Cards from `tblAccountSnapshot`:

- `CurrentEquitySEK`
- `TotalPnLSEK`
- `WinRatePct`
- `OpenForTradeCount`
- `OpenTradeCount`
- `LastCompletedBar`

Open-for-trade table from `tblLiveTradeStatus` filtered to:

- `IsPrimary = True`
- `IsOpenForTrade = True`

Recommended columns:

- `Ticker`
- `Direction`
- `EntryPrice`
- `CurrentPrice`
- `StopPrice`
- `TargetPrice`
- `TradeStatus`

Currently traded table from `tblLiveTradeStatus` filtered to:

- `IsPrimary = True`
- `IsCurrentlyTraded = True`

Recommended columns:

- `Ticker`
- `TradeStatus`
- `EntryTime`
- `EntryPrice`
- `CurrentPrice`
- `StopPrice`
- `TargetPrice`
- `UnrealizedPnLSEK`

Completed-trade table and date slicer from `tblTradeHistory`:

- slicer: `SessionDate`
- table fields: `Ticker`, `EntryTime`, `EntryPrice`, `StopPrice`, `TargetPrice`, `ExitTime`, `ExitPrice`, `ExitReason`, `NetPnLSEK`, `RecordStatus`

## Notes

- Current price means the close of the latest completed five-minute bar, not a tick quote.
- The exact engine uses conservative STOP priority when both stop and target occur in the same bar.
- At EOD, the normal Step 9L evaluator remains authoritative.
