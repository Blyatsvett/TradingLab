# Step 9S Prospective Contingency Shadow V1

Status: `RESEARCH_ONLY_PROSPECTIVE_COMPLETE_TRADE_COVERAGE_NOT_ROUTER_ACTIVE`

## Purpose

Step 9S tests the Contingency Trading thesis on unseen mornings. It reads the immutable Step 9L V3 morning regime, assigns the frozen natural strategy for that regime, and seals one mandatory shadow-control plan so every recognized session produces an EOD trade observation.

Natural and mandatory-control trades are stored in separate books. Mandatory controls must never be interpreted as natural signals.

## Point-in-time timing

- Regime decision: 09:45, inherited from sealed Step 9L V3.
- Step 9S assignment deadline: 09:49:30 Stockholm time.
- Mandatory control entry: first available 5-minute bar open from 09:50 through 10:00.
- Latest morning feature bar: 09:40.
- EOD requires data through at least the 16:25-labelled bar.

The historical Step 9S V1 prototype entered at 09:45. Prospective V1 intentionally uses 09:50 because Step 9S is assigned only after the Step 9L morning seal; using the 09:45 open prospectively would be retrospective.

## Separate immutable ledger

`data\step9s_prospective_contingency_shadow_v1.db`

SQLite triggers reject UPDATE and DELETE operations. Identical morning/EOD reruns return existing rows; conflicting reruns fail.

## Outputs

`data\step9s_prospective_contingency_shadow_v1\`

- `step9s_prospective_assignments.csv`
- `step9s_prospective_coverage_plans.csv`
- `step9s_prospective_outcome_batches.csv`
- `step9s_prospective_natural_outcomes.csv`
- `step9s_prospective_coverage_outcomes.csv`
- `step9s_prospective_summary.csv`
- `step9s_prospective_audit.csv`
- `step9s_prospective_assignment_registry.csv`

## Normal morning order

1. Run the 29-ticker collector after the completed 09:40 bar is available.
2. Confirm 29/29 tickers.
3. Run Step 9I V2 morning once.
4. Run Step 9L V3 morning once.
5. Run `./run_step9s_prospective_morning.ps1` before 09:49:30.
6. Run Step 9Q snapshot and refresh Power BI.

Do not rerun Step 9I or Step 9L because Step 9S fails. Repair or reconstruct Step 9S separately and label late reconstruction non-confirmatory.

## Normal EOD order

1. Run the final collector.
2. Run Step 9I V2 EOD.
3. Run Step 9L V3 EOD.
4. Run `./run_step9s_prospective_eod.ps1`.
5. Run Step 9Q final snapshot and refresh Power BI.

Step 9S EOD requires the sealed Step 9L outcome batch first.

## Safety

- Router inactive.
- Orders disabled.
- No broker or execution connection.
- Step 9I, Step 9L, Step 9Q, Step 9R, ORB, and their ledgers are read-only to Step 9S.
- Historical Step 9S replay/freeze outputs are read only.
