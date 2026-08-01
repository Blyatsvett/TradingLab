STEP 9D - REGIME × STRATEGY CHALLENGER MATRIX
=============================================

Purpose
-------
Step 9D freezes the Step 9B routed baseline as a control and runs nine
pre-registered, point-in-time-safe strategy hypotheses across every observed
Step 8 regime. It is a discovery comparison, not parameter optimization and
not a final strategy-selection step.

Registered comparison rows
--------------------------
1. Frozen Step 9B routed baseline control
2. Strict gap recovery across all regimes
3. Immediate opening-range continuation, 1R
4. Close-confirmed opening-range continuation, 1R
5. Range rejection/reversion, 1.25R
6. Early-move continuation, 1.5R
7. Delayed early-move reversal, 1R
8. Directional volatility breakout, 2R
9. Relative-strength pair continuation
10. Pair spread convergence

Risk comparison
---------------
Every generated trade reports two research-only P&L models:

- Equal notional: current baseline notional scaled by the Step 8 regime risk
  multiplier.
- Fixed-risk capped: the same maximum notional, but reduced when the initial
  stop risk would exceed a 5 SEK full-risk budget before regime scaling.

This lets the diagnostics distinguish strategy logic from the unequal monetary
risk found in Step 9C. It never increases notional above the existing baseline.

Run
---
From the project root:

    .\run_step9d_regime_strategy_challenger_matrix.ps1

Or run the full workflow:

    .\run_regime_research.ps1

Outputs
-------
- data\regime_challenger_matrix_summary.csv
- data\regime_challenger_registry.csv
- data\regime_challenger_candidates.csv
- data\regime_challenger_trades.csv
- data\regime_challenger_trade_legs.csv
- data\regime_challenger_performance.csv
- data\regime_challenger_rankings.csv
- data\regime_challenger_session_coverage.csv
- data\regime_challenger_audit.csv

Interpretation guardrails
-------------------------
- A cell is only screenable with at least 8 trades across at least 4 sessions.
- Rankings are discovery evidence only.
- The code promotes zero strategies by design.
- Positive in-sample cells require chronological robustness and new forward
  sessions before any router choice can be frozen.
- The frozen legacy V1 remains ineligible for the future router.

Expected mechanical classification
----------------------------------

    REGIME_STRATEGY_CHALLENGER_MATRIX_READY_FOR_DISCOVERY_REVIEW
