# STEP9T_REGIME_TRANSITION_ARCHETYPE_RESEARCH_V1

Status: `RESEARCH_ONLY_READ_ONLY_NOT_ROUTER_ACTIVE`

Step 9T preserves the immutable opening regime, calculates a separate 09:50
transition snapshot from bars labelled through 09:45, classifies all 29 tickers
into deterministic strategy archetypes, and evaluates standardized 09:50-to-EOD
counterfactual outcomes.

It does not alter Step 9I, Step 9L, Step 9Q, Step 9R, Step 9S, ORB, or any
existing ledger. It sends no orders.

## Historical V1 outputs

Written only under:

`data/step9t_regime_transition_archetype_research_v1/`

- `step9t_session_transitions.csv`
- `step9t_ticker_archetypes.csv`
- `step9t_ticker_outcomes.csv`
- `step9t_regime_summary.csv`
- `step9t_transition_summary.csv`
- `step9t_archetype_summary.csv`
- `step9t_ticker_summary.csv`
- `step9t_audit.csv`
- `step9t_summary.csv`
- `step9t_source_hashes.json`

All historical rows, including July 28, are labelled
`RETROSPECTIVE_NON_CONFIRMATORY_DIAGNOSTIC`.

## Point-in-time rule

- Morning features may use bars labelled no later than 09:45.
- The 09:50 bar open is the standardized diagnostic entry price.
- The 09:50 high, low, and close do not influence morning classification.
- The original opening regime is copied and never rewritten.

## July 28 interpretation

The 09:50 snapshot reproduces `WEAKNESS_PERSISTING`, because the broad upward
recovery developed after the 09:50 decision point. The later outcome data then
shows which bearish-continuation diagnostics failed and which other directional
archetypes would have profited.

## V1 boundary

This version observes and records only. It does not change the same-day Step 9S
mandatory trade or Step 9R candidate selections. Prospective runners are a
separate later phase after the historical outputs are audited and frozen.
