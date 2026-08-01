# STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1

## Status

`RESEARCH_ONLY_RETROSPECTIVE_IN_SAMPLE_RULE_DESIGN_NOT_ROUTER_ACTIVE`

Step 9U V1 is a new challenger. It does not replace or modify Step 9S V1, Step 9R V1.1, Step 9T, Step 9L V3, or Step 9I V2.

## Purpose

Use the frozen Step 9T historical transition/archetype dataset to test a deterministic contingency-selection policy that:

- preserves every morning-complete directional Step 9T candidate;
- applies frozen positive-challenger and negative-control rules;
- ranks candidates using morning-only information;
- selects zero to two shadow positions per session;
- limits selection to one ticker per broad sector;
- attaches every candidate's frozen Step 9T counterfactual outcome;
- compares coverage with Step 9S without treating unlike execution contracts as directly comparable.

## Frozen source

- Step 9T freeze ID: `92b274cb24cad391`
- Artifact-set SHA-256: `92b274cb24cad391324b4023e20c9f9830544f6c63e87b73846ff757ff986aa1`
- Independent Step 9T audit: `30/30 PASSED`

## V1 rule registry

### 1. Laggard-recovery challenger

- Rule ID: `LRL_AGGREGATE_PROMISING_V1`
- Match: `LAGGARD_RECOVERY_LONG`
- Regime: any
- Transition: any
- Action: selectable challenger
- Priority: 200
- Signal strength: `max(-early_return, 0) + max(last5_return, 0)`

Evidence basis: promising aggregate Step 9T archetype evidence. Exact regime-transition cells remain sparse.

### 2. Volatility-expansion bullish-continuation challenger

- Rule ID: `VE_BCL_BACKOFF_CHALLENGER_V1`
- Match: `VOLATILITY_EXPANSION × BULLISH_CONTINUATION_LONG`
- Transition: any
- Action: selectable challenger
- Priority: 100
- Signal strength: `max(early_return, 0) + max(last5_return, 0)`

Evidence basis: exploratory regime-archetype backoff result. It is not prospectively validated.

### 3. Negative-control block

- Rule ID: `HD_MIXED_BCL_AVOID_V1`
- Match: `HIGH_DISPERSION × MIXED_TRANSITION × BULLISH_CONTINUATION_LONG`
- Action: blocked negative control

Evidence basis: the frozen exact Step 9T cell had a session-clustered confidence interval below zero.

### 4. All other directional archetypes

- Action: `OBSERVATION_ONLY`
- They remain in the candidate and counterfactual-outcome dataset.
- They cannot be selected by V1.

## Deterministic ranking

1. Rule priority, descending
2. Signal strength, descending
3. Ticker, ascending

Risk constraints:

- maximum selected positions: 2;
- maximum positions per broad sector: 1;
- mandatory coverage control: disabled;
- router: inactive;
- orders: disabled.

## Outcome contract

Step 9U V1 inherits the frozen Step 9T standardized diagnostic outcome:

- entry: 09:50 bar open;
- exit: final available session close;
- notional: 1,000 SEK per candidate;
- frozen Step 9T transaction cost;
- MFE and MAE preserved.

This is not the same execution contract as Step 9S. P&L values must not be directly compared as if they were identical strategies.

## Historical interpretation boundary

The Step 9U rules were designed from the same frozen Step 9T historical dataset used by this replay. Therefore:

- all results are retrospective and in-sample;
- historical P&L is a design diagnostic, not evidence of deployable edge;
- no rule may be promoted based on this replay;
- prospective Step 9U rules must be frozen before the first unseen session.

## Output files

`data/step9u_historical_contingency_selector_v1/`

- `step9u_policy_registry.csv`
- `step9u_session_assignments.csv`
- `step9u_all_candidates.csv`
- `step9u_selected_outcomes.csv`
- `step9u_performance.csv`
- `step9u_selection_regret.csv`
- `step9u_daily_pnl.csv`
- `step9u_step9s_benchmark_comparison.csv`
- `step9u_audit.csv`
- `step9u_summary.csv`
- `step9u_source_hashes.json`

## Acceptance gate

- dedicated tests pass;
- deterministic verifier passes;
- 970 directional candidates preserved;
- 158 selectable candidates;
- 79 blocked negative-control candidates;
- zero to two selections per session;
- maximum one selection per sector;
- all candidate outcomes preserved;
- 30/30 independent audit;
- protected files byte-for-byte unchanged;
- complete project suite passes;
- no order sent.

## Feasible-oracle diagnostic hotfix

`step9u_selection_regret.csv` uses a future-information diagnostic oracle that may select zero to two positive candidates and obeys the same maximum-one-position-per-sector constraint as Step 9U. It never influences selection. The resulting opportunity cost is non-negative by construction.

