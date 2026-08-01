# STEP 9 KPI Evaluation Specification V1

**Specification ID:** `STEP9KPI_READ_ONLY_EVALUATION_V1`  
**Status:** `PROPOSED_LOCK_CANDIDATE_NOT_IMPLEMENTED`  
**Date:** 2026-07-29  
**Scope:** Step 9I, 9L, 9S, 9R, 9T, 9U and 9V research/shadow outputs  
**Safety:** Read-only reporting and evaluation. No selector, router, production ORB, frozen strategy, morning ledger or EOD outcome is modified.

---

## 1. Purpose

The KPI layer must answer six questions:

1. How did each engine/book perform versus the best observed two-ticker benchmark?
2. Was the best available strategy chosen for each ticker?
3. Did the morning regime match the independently classified realized EOD regime?
4. Was the selected strategy appropriate for the realized regime, and which alternative regime-compatible strategy performed best?
5. Did the morning ranking put the best realized tickers at the top, and what opportunity was lost?
6. Would a position cap of 1, 2, 3 or 4 tickers have produced a better daily result?

All hindsight calculations are explicitly counterfactual and must never be presented as selected-book performance.

---

## 2. Locked global conventions

| Item | V1 rule |
|---|---|
| Comparison currency | SEK |
| Comparison notional | 1,000 SEK per ticker-strategy position |
| Comparison round-trip cost | 0.0005 of comparison notional, unless a strategy has no completed trade |
| Daily engine P&L | Sum of standardized net P&L for the engine's actual selected/completed positions |
| Native P&L | Source-ledger P&L retained separately and never mixed with standardized P&L |
| Main portfolio cap | 2 unique tickers |
| Portfolio-size study | N = 0, 1, 2, 3, 4 |
| Duplicate ticker rule | One ticker may appear at most once in a portfolio |
| Feasible benchmark sector rule | Preserve the source engine's locked sector rule; Step 9U uses max one position per broad sector |
| Missing engine session | Blank / not evaluable, not zero |
| Valid no-trade session | Zero P&L when the engine completed normally and selected no trade |
| P&L tie tolerance | 0.01 SEK |
| Main evidence filter | `PROSPECTIVE_CONFIRMATORY` only; mock and historical views remain available through slicers |
| Source access | SQLite `mode=ro` and `PRAGMA query_only=ON` |

### 2.1 Evidence status enum

- `PROSPECTIVE_CONFIRMATORY`
- `PROSPECTIVE_EXCLUDED`
- `MOCK_REHEARSAL`
- `HISTORICAL_RETROSPECTIVE`

July 29, 2026 is `MOCK_REHEARSAL`.

### 2.2 Result type enum

- `ACTUAL_SELECTED`
- `NATURAL_BOOK`
- `MANDATORY_CONTROL`
- `CANDIDATE_COUNTERFACTUAL`
- `OBSERVER_COUNTERFACTUAL`
- `ORACLE_BENCHMARK`
- `CASH_NO_TRADE`

---

## 3. Canonical engine and book definitions

The main benchmark chart may contain only portfolios with a comparable position cap or an explicitly labelled benchmark.

| Engine/book ID | Main chart | Result type | Notes |
|---|---:|---|---|
| `STEP9I_V2_SELECTED` | Yes | ACTUAL_SELECTED | Frozen Step 9I V2 selected simulation book |
| `STEP9L_V3_SELECTED` | Yes | ACTUAL_SELECTED | Frozen Step 9L V3 selected book |
| `STEP9S_NATURAL` | Yes | NATURAL_BOOK | Keep separate from control |
| `STEP9S_MANDATORY_CONTROL` | Yes | MANDATORY_CONTROL | Exactly one benchmark/control plan where applicable |
| `STEP9R_SELECTED` | Yes | ACTUAL_SELECTED | May validly select zero |
| `STEP9U_SELECTED` | Yes | ACTUAL_SELECTED | Max 2, max 1 per broad sector |
| `STEP9U_PLUS_STEP9V_ACTION` | Optional dashed line | OBSERVER_COUNTERFACTUAL | Never actual selected performance in V1 |
| `STEP9T_ALL_DIRECTIONAL` | No | CANDIDATE_COUNTERFACTUAL | Too many simultaneous positions for the main chart; use diagnostics only |

Step 9S natural and mandatory control must never be silently added together. A combined diagnostic may be shown only as `STEP9S_COMBINED_DIAGNOSTIC`.

---

## 4. Canonical strategy-outcome normalization

### 4.1 Canonical strategy variant IDs

- Step 9L contract: `STEP9L::<contract_id>`
- Step 9T archetype hold: `STEP9T::<primary_archetype>::0950_TO_EOD`
- Step 9S control: `STEP9S_CONTROL::<coverage_control_id>`
- Step 9V management: `STEP9V::<base_rule_id>::<checkpoint_time>::<KEEP|REDUCE|EXIT|SWITCH>`
- No trade: `CASH_NO_TRADE`

### 4.2 Canonical outcome key

`session_date + ticker + strategy_variant_id + direction + entry_time + exit_time`

### 4.3 Duplicate-source precedence

The same economic trade can appear in multiple ledgers. For strategy comparison it must be counted once using this precedence:

1. Authoritative strategy EOD ledger, such as Step 9L for a Step 9L contract
2. Step 9T for archetype 09:50-to-EOD outcomes
3. Step 9S coverage ledger for mandatory controls
4. Step 9V for checkpoint-management variants
5. Step 9R candidate outcome only when no authoritative Step 9L outcome exists
6. Step 9S natural outcome only when no authoritative natural-source outcome exists

Multiple engine memberships are retained in a bridge table; they do not create duplicate oracle candidates.

### 4.4 Standardized P&L

For a completed single-ticker trade:

`standardized_gross_pnl_sek = direction_adjusted_gross_return * 1000`

`standardized_cost_sek = 1000 * 0.0005 = 0.50 SEK`

`standardized_net_pnl_sek = standardized_gross_pnl_sek - standardized_cost_sek`

For no trigger/no trade: standardized P&L and cost are zero.  
For incomplete outcomes: standardized P&L is null and excluded from accuracy/oracle calculations.

Pair strategies must be normalized to 1,000 SEK total pair notional, split according to the strategy's locked leg allocation.

---

## 5. KPI 1 — Engine performance and benchmark strategies

### 5.1 Daily engine P&L

**Grain:** one row per session, engine, book and evidence status.

`daily_standardized_net_pnl_sek = sum(standardized_net_pnl_sek for actual selected completed positions)`

The Power BI cumulative line is a date-aware cumulative sum of this daily field. It is not stored as a fixed column because slicers must recalculate it.

### 5.2 Requested oracle benchmark

**Benchmark ID:** `ORACLE_TOP2_OBSERVED_FIXED`

Algorithm:

1. Start with all complete, deduplicated ticker-strategy outcomes in the approved observed strategy universe.
2. For each ticker, choose the strategy with the highest standardized net P&L.
3. Break a strategy tie within 0.01 SEK by `strategy_variant_id ASC`.
4. Rank the resulting unique tickers by best standardized net P&L descending, then `ticker ASC`.
5. Choose exactly the top two tickers when at least two are available.
6. Sum their standardized net P&L.

This is hindsight and must be labelled `ORACLE_BENCHMARK`.

### 5.3 Required companion benchmarks

- `ORACLE_UP_TO2_OBSERVED_NO_FORCE`: choose only positive outcomes, up to two; cash is allowed.
- `ORACLE_TOP2_FEASIBLE_FIXED`: exactly two, restricted to morning-available strategies and the applicable portfolio constraints.
- `ORACLE_UP_TO2_FEASIBLE_NO_FORCE`: feasible, positive-only, up to two.

The user's requested main benchmark line is `ORACLE_TOP2_OBSERVED_FIXED`. The no-force and feasible variants are required so the chart does not hide the effect of forced trading or governance constraints.

### 5.4 Required visuals

- Line chart: date on X, cumulative standardized net P&L on Y, engine/book/benchmark as legend
- Clustered column chart: daily standardized P&L by engine/book
- Mandatory slicers: evidence status, engine, book type, session date

---

## 6. KPI 2 — Strategy accuracy

### 6.1 Two distinct accuracy measures

#### A. Selected-ticker strategy accuracy

Among tickers actually selected by an engine, did the applied strategy equal the best observed strategy for that ticker?

#### B. Full ticker-decision accuracy

For every ticker in the engine's decision universe, did the engine choose the best action when `CASH_NO_TRADE` with P&L 0 is included as an alternative?

This allows a correct no-trade decision to receive credit and exposes rejected winners.

### 6.2 Oracle strategy per ticker

For each session/ticker:

`oracle_best_strategy_pnl = max(0, all complete approved strategy outcomes for the ticker)` for no-force decision accuracy.

The oracle tie set contains all strategies within 0.01 SEK of the maximum.

### 6.3 Classification enum

- `APPLIED_BEST_STRATEGY`
- `APPLIED_TIED_BEST_STRATEGY`
- `APPLIED_NOT_BEST`
- `NO_TRADE_CORRECT`
- `NO_TRADE_FALSE_NEGATIVE`
- `TRADE_FALSE_POSITIVE_VS_CASH`
- `NOT_EVALUABLE`

### 6.4 Formulas

`strategy_correct_flag = 1` when the applied strategy is in the oracle tie set.

`strategy_opportunity_loss_sek = max(0, oracle_best_strategy_pnl_sek - applied_strategy_pnl_sek)`

`selected_ticker_strategy_accuracy_pct = correct selected tickers / evaluable selected tickers`

`full_decision_accuracy_pct = correct actions including cash / evaluable ticker decisions`

### 6.5 Required visuals

- Matrix: ticker, applied strategy, best strategy, applied P&L, best P&L, opportunity loss, classification
- Cards: selected-ticker accuracy %, full-decision accuracy %, total strategy opportunity loss
- Bar chart: opportunity loss by applied strategy

---

## 7. KPI 3 — Regime accuracy

### 7.1 Independent realized EOD regime

**Classifier ID:** `REALIZED_EOD_REGIME_V1`  
**Status:** research-only adjudication; never available to morning selectors.

The exact-match KPI compares the morning regime with an independently classified EOD market state. Strategy profitability is not used to classify the EOD regime.

### 7.2 Universe and timestamps

Primary classifier universe: the same frozen regime-source ticker set used by the morning regime engine, not the full 29-ticker strategy universe.  
Diagnostic classifier: the full 29 tickers, stored separately.

Required labels:

- Opening reference: 09:00
- Morning reference: 09:40
- EOD reference: latest completed bar at or after 17:20, normally 17:25

Minimum coverage: at least 80% of the configured regime-source universe with all required labels. Otherwise the result is `DATA_LIMITED_DEFENSIVE`.

### 7.3 EOD features

- median opening gap and gap-down/gap-up shares
- median return from open at 09:40
- median return from open at EOD
- advancer and decliner shares at EOD
- median post-09:40 return
- median full-session high-low range divided by open
- median five-minute realized volatility
- cross-sectional dispersion of EOD returns
- directional path persistence
- prior-20-session percentiles for range, realized volatility and dispersion; minimum five prior sessions

`directional_path_persistence` is the share of completed five-minute equal-weight market returns whose sign matches the final EOD median-return direction, excluding zero intervals.

`reversal_strength`:

- 1.0 when the 09:40 median return and EOD median return are both at least 0.10% in magnitude and have opposite signs;
- otherwise, when they share a sign and EOD magnitude is smaller, `1 - abs(eod_return)/abs(morning_return)`;
- otherwise 0.

### 7.4 Deterministic priority rules

Rules are evaluated in this order; the first true rule is the realized regime.

1. **DATA_LIMITED_DEFENSIVE**  
   Coverage below 80% or required EOD labels incomplete.

2. **RECOVERY**  
   Median opening gap <= -0.30%; gap-down share >= 55%; EOD median return >= +0.20%; post-09:40 median return > 0; advancer share >= 55%.

3. **HIGH_VOL_REVERSAL**  
   Max(realized-range percentile, realized-volatility percentile) >= 75%; reversal strength >= 0.70; abs(09:40 median return) >= 0.15%.

4. **VOLATILITY_EXPANSION**  
   Max(realized-range percentile, realized-volatility percentile) >= 75%; abs(EOD median return) >= 0.40%; max(advancer share, decliner share) >= 60%.

5. **TREND_UP**  
   EOD median return >= +0.40%; advancer share >= 60%; path persistence >= 60%.

6. **TREND_DOWN**  
   EOD median return <= -0.40%; decliner share >= 60%; path persistence >= 60%.

7. **HIGH_DISPERSION**  
   EOD return-dispersion percentile >= 75%; advancer share between 35% and 65% inclusive.

8. **RANGE_LOW_VOL**  
   Max(realized-range percentile, realized-volatility percentile) <= 25%; abs(EOD median return) <= 0.20%; advancer share between 35% and 65% inclusive; dispersion percentile <= 50%.

9. **DEFENSIVE_MIXED**  
   Default when no specialist rule is satisfied.

The output must store every rule flag, the winning rule ID, and the number of rules that were true before priority resolution.

### 7.5 Accuracy states

- `EXACT_MATCH`
- `MISMATCH`
- `MORNING_DATA_LIMITED`
- `EOD_DATA_LIMITED`
- `NOT_EVALUABLE`

Primary card values:

- Morning regime
- Realized EOD regime
- Match state

No numeric accuracy is required on the daily card. A confusion matrix is required once multiple sessions exist.

---

## 8. KPI 4 — Strategy plus regime accuracy

This KPI separates two questions that must not be conflated.

### 8.1 Regime compatibility

Was every selected strategy registered as applicable to the realized EOD regime?

`regime_compatible_flag = 1` when all selected strategy variants are allowed for the realized EOD regime in the frozen strategy registry.

### 8.2 Economic best-strategy match

Did the selected strategy portfolio equal the best observed regime-compatible strategy portfolio?

For each realized regime and session:

1. Evaluate each registered compatible strategy using its own point-in-time candidate ranking and portfolio constraints.
2. Build that strategy's up-to-two no-force standardized portfolio.
3. Choose the strategy portfolio with the highest standardized net P&L.
4. Compare the selected engine portfolio with the best compatible strategy portfolio.

The strategy's own frozen ranking must be used. Hindsight ticker selection is reported separately and cannot be used for the main strategy+regime accuracy flag.

### 8.3 Fields and formulas

- morning regime
- realized EOD regime
- selected strategy set
- official frozen strategy mapped to the realized regime
- best observed compatible strategy
- selected strategy portfolio P&L
- official mapped-strategy portfolio P&L
- best compatible strategy portfolio P&L

`regime_strategy_opportunity_loss_sek = max(0, best_compatible_strategy_pnl - selected_strategy_pnl)`

### 8.4 Accuracy states

- `COMPATIBLE_AND_BEST`
- `COMPATIBLE_NOT_BEST`
- `INCOMPATIBLE_BUT_PROFITABLE`
- `INCOMPATIBLE_AND_NOT_BEST`
- `NO_TRADE_BEST`
- `NOT_EVALUABLE`

### 8.5 Required visuals

- Daily selected vs official-mapped vs best-compatible P&L columns
- Heatmap: realized EOD regime by strategy, value = average standardized P&L
- Table: alternative strategies and their daily standardized P&L

---

## 9. KPI 5 — Ranking quality

### 9.1 Candidate-set rule

Ranking is evaluated only within the engine's own frozen morning candidate set. The KPI layer may not invent scores or ranks for unranked observation-only tickers.

### 9.2 Actual rank

Candidates are ranked by realized standardized net P&L descending. Outcomes within 0.01 SEK share a dense rank; an ordinal rank is also produced using `ticker ASC` as the deterministic tie-break.

### 9.3 Ticker-level metrics

- predicted rank
- predicted score
- actual dense rank
- actual ordinal rank
- rank error = predicted ordinal rank - actual ordinal rank
- absolute rank error
- selected flag
- standardized P&L
- winner flag

### 9.4 Daily metrics

- Spearman rank correlation when at least three complete ranked candidates exist
- Top-1 hit flag
- Top-2 overlap count and percentage
- Selected portfolio P&L
- Predicted top-cap portfolio P&L, ignoring the no-trade threshold but retaining constraints
- Oracle fixed-cap portfolio P&L
- Oracle up-to-cap no-force portfolio P&L

`ranking_regret_fixed_cap_sek = oracle_fixed_cap_pnl - predicted_top_cap_pnl`

`total_selection_opportunity_loss_sek = max(0, oracle_up_to_cap_no_force_pnl - actual_selected_pnl)`

`threshold_effect_vs_forced_rank_sek = actual_selected_pnl - predicted_top_cap_pnl`

Interpretation of threshold effect:

- positive: the threshold avoided bad forced selections;
- negative: the threshold rejected profitable ranked candidates.

### 9.5 Required visuals

- Scatter: predicted rank/score versus realized P&L
- Table: predicted rank, actual rank, selected flag, P&L and rank error
- Cards: Top-2 overlap %, ranking regret, total selection opportunity loss, threshold effect

---

## 10. KPI 6 — Number-of-tickers sensitivity

### 10.1 N values

Evaluate N = 0, 1, 2, 3 and 4.

N=0 is cash with zero P&L.

### 10.2 Simulation modes

1. `ENGINE_RANKED_FIXED_N`  
   Exactly N candidates by frozen morning predicted rank, retaining engine constraints. Requires at least N ranked complete candidates.

2. `ENGINE_POLICY_UP_TO_N`  
   Apply the engine's frozen eligibility/threshold rules, then cap at N.

3. `ORACLE_FIXED_N`  
   Exactly N candidates by realized standardized P&L, retaining the same candidate set and constraints.

4. `ORACLE_UP_TO_N_NO_FORCE`  
   Up to N positive realized candidates, retaining constraints; cash allowed.

No rank may be invented. If an engine provides only two ranked candidates, engine-ranked N=3 and N=4 are `NOT_EVALUABLE`; oracle diagnostics may still be available.

### 10.3 Metrics per N

- selected ticker count
- total standardized P&L
- average P&L per ticker
- capital deployed
- return on deployed capital
- winners, losers and win rate
- worst individual P&L
- portfolio constraints applied
- evaluation status

Daily best N is produced twice:

- `best_n_by_total_pnl`
- `best_n_by_return_on_deployed_capital`

Tie-break: lower N wins when values are within 0.01 SEK for P&L or 0.000001 for return.

### 10.4 Required visuals

- X-axis N, Y-axis total daily standardized P&L, legend engine/simulation mode
- Secondary chart for return on deployed capital
- Card: best N by total P&L

---

## 11. Output model

The KPI layer publishes both machine-readable files and a Power BI workbook.

### 11.1 Proposed output location

`data\outputs\kpi\`

### 11.2 Proposed files

- `step9kpi_session.csv`
- `step9kpi_engine_daily.csv`
- `step9kpi_benchmark_daily.csv`
- `step9kpi_strategy_outcome.csv`
- `step9kpi_strategy_accuracy.csv`
- `step9kpi_regime_accuracy.csv`
- `step9kpi_regime_strategy_accuracy.csv`
- `step9kpi_ranking_ticker.csv`
- `step9kpi_ranking_daily.csv`
- `step9kpi_portfolio_size.csv`
- `step9kpi_data_quality.csv`
- `powerbi_step9_kpi_monitor.xlsx`

### 11.3 Power BI named tables

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

The exact column-level schema is in `STEP9_KPI_OUTPUT_SCHEMA_V1_20260729.json`.

---

## 12. Mandatory data-quality and safety checks

1. Every source database opens read-only.
2. Source hashes are captured before and after; all source files must remain byte-for-byte unchanged.
3. Every actual selected engine row reconciles to its authoritative EOD batch.
4. Oracle outcomes are deduplicated by canonical outcome key.
5. Every benchmark has a coverage count and coverage status.
6. No incomplete outcome contributes P&L or accuracy.
7. Mock/historical sessions cannot enter confirmatory measures without explicit evidence-status filtering.
8. Step 9S natural and control books remain separate.
9. Step 9T all-directional P&L is excluded from the main engine-comparison chart.
10. Step 9V outcomes remain observer counterfactuals.
11. Workbook publication is atomic; failed validation does not replace the last valid workbook.
12. Router active and order sent must remain false in every source and output audit.

---

## 13. July 29 mock validation fixtures

These values are test fixtures only and remain non-confirmatory:

- Step 9L selected native P&L: approximately +3.092 SEK
- Step 9S mandatory control native P&L: approximately +3.951 SEK
- Step 9R selected P&L: 0 SEK; rejected-candidate opportunity approximately +3.092 SEK
- Step 9U selected native P&L: approximately +7.454 SEK
- Step 9U observed unrestricted best two unique tickers: ABB.ST and GETI-B.ST, approximately +27.703 SEK under the existing 1,000-SEK archetype outcomes
- Step 9V 15:00 ticker-specific hindsight: exit SAND.ST and hold GETI-B.ST outperformed holding both

The implementation must reproduce authoritative native values and then separately calculate standardized comparison values.

---

## 14. Freeze boundary

Approval of this specification freezes definitions and schemas only. It does **not**:

- modify any morning or EOD engine;
- promote a strategy;
- activate Step 9V actions;
- enable a router;
- make mock or historical evidence confirmatory.

Any later KPI-definition change requires a new version ID, not an in-place rewrite.
