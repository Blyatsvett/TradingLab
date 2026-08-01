# Step 9 KPI Read-Only Evaluation V1

## Status

`STEP9KPI_READ_ONLY_EVALUATION_V1`

`READ_ONLY_KPI_EVALUATION_NOT_SELECTOR_NOT_ROUTER_ACTIVE`

This layer evaluates completed Step 9 outcomes. It does not alter morning decisions, EOD outcomes, source databases, positions, routers, orders, or the frozen ORB production system.

## Source contract

All SQLite inputs are opened with `mode=ro` and `PRAGMA query_only=ON`. Source SHA-256 hashes are captured before and after every build. Publication stops if the exact output schema is not satisfied. CSVs and the Excel workbook are replaced atomically only after validation.

## Comparison convention

- Currency: SEK
- Standardized notional: 1,000 SEK per position
- Standardized round-trip cost: 0.0005 of notional
- Native source-ledger P&L remains available separately
- Evidence status remains explicit: confirmatory, excluded, mock, or historical

## Benchmark clarification

The approved specification contains one internal conflict:

- Section 5 defines `ORACLE_TOP2_OBSERVED_FIXED` as the best two unique ticker-strategy outcomes without a sector cap.
- The July 29 fixture names ABB.ST and GETI-B.ST, which requires the Step 9U maximum-one-position-per-sector rule.

The implementation preserves both interpretations instead of silently choosing one:

- `ORACLE_TOP2_OBSERVED_FIXED`: true unrestricted main benchmark.
- `ORACLE_TOP2_OBSERVED_SECTOR_CAPPED_FIXED`: same observed oracle with maximum one ticker per broad sector.

For the July 29 mock fixture:

- unrestricted: ABB.ST + ATCO-A.ST, approximately +28.160371 standardized SEK;
- sector-capped: ABB.ST + GETI-B.ST, approximately +27.702846 standardized SEK.

## Output

Default folder:

`data\outputs\kpi`

Default workbook:

`data\outputs\kpi\powerbi_step9_kpi_monitor.xlsx`

Named Power BI tables:

- `dimSession`
- `dimEngine`
- `dimStrategy`
- `tblEngineDaily`
- `tblBenchmarkDaily`
- `tblStrategyOutcome`
- `tblStrategyAccuracy`
- `tblRegimeAccuracy`
- `tblRegimeStrategyAccuracy`
- `tblRankingTicker`
- `tblRankingDaily`
- `tblPortfolioSize`
- `tblDataQuality`

The same tables are also published as UTF-8 CSV files.

## Run after EOD

From the activated project root:

```powershell
.\run_step9kpi_read_only_evaluation_v1.ps1
```

Specific session:

```powershell
.\run_step9kpi_read_only_evaluation_v1.ps1 -Date "2026-07-29"
```

Run the ordinary Step 9 EOD engines first. The KPI layer reads their completed outcomes; it is not an EOD evaluator itself.

## Super-simple Power BI connection

1. Open Power BI Desktop.
2. Select **Get data → Excel workbook**.
3. Select `data\outputs\kpi\powerbi_step9_kpi_monitor.xlsx`.
4. Load all named tables.
5. Create one-to-many relationships from `dimSession` to fact tables on `session_date` and `evidence_status` where practical.
6. Relate `dimEngine[engine_book_id]` to engine/ranking/portfolio tables.
7. Relate `dimStrategy[strategy_variant_id]` to strategy-outcome and strategy-accuracy tables.
8. Add slicers for date, evidence status, engine/book, strategy, and benchmark ID.

### Main cumulative P&L measure

```DAX
Cumulative Standardized PnL SEK =
VAR CurrentDate = MAX(dimSession[session_date])
RETURN
CALCULATE(
    SUM(tblEngineDaily[standardized_net_pnl_sek]),
    FILTER(
        ALLSELECTED(dimSession[session_date]),
        dimSession[session_date] <= CurrentDate
    )
)
```

Create a parallel benchmark measure from `tblBenchmarkDaily[standardized_net_pnl_sek]`, or append engine and benchmark rows in Power Query into one chart fact table.

### Recommended pages

1. Executive daily overview
2. Engine and oracle cumulative P&L
3. Strategy accuracy and opportunity loss
4. Morning versus realized EOD regime
5. Regime-strategy compatibility
6. Ranking quality
7. Portfolio-size sensitivity for N = 0–4
8. Data-quality and evidence-status audit

## July 29 fixture

The included verifier checks:

- Step 9L native P&L approximately +3.092064 SEK
- Step 9S mandatory control native P&L approximately +3.950943 SEK
- Step 9R selected P&L 0 SEK
- Step 9U native P&L approximately +7.453895 SEK
- unrestricted oracle top two ABB.ST + ATCO-A.ST
- sector-capped oracle top two ABB.ST + GETI-B.ST
- morning regime RANGE_LOW_VOL
- realized EOD regime DEFENSIVE_MIXED
- all data-quality checks pass
- source ledgers remain byte-for-byte unchanged
- router and orders remain disabled

July 29 remains `MOCK_REHEARSAL` and contributes no confirmatory evidence.

## V1.1 unified evidence feed hotfix

The default PowerShell wrapper now searches the sibling `Regime trading mock sessions` folder for the completed July 29 rehearsal and appends only session `2026-07-29` from that isolated clone. The appended rows retain `evidence_status = MOCK_REHEARSAL`; they never become confirmatory and are never merged back into a trading ledger.

Use the ordinary command for the unified workbook:

```powershell
.\run_step9kpi_read_only_evaluation_v1.ps1
```

Use `-SkipJuly29Mock` only when a deliberately real-only export is needed. A specific mock clone can be supplied through `-July29MockProjectRoot`.
