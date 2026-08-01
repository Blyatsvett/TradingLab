STEP 9I-R — HISTORICAL WALK-FORWARD REPLAY
==========================================

Purpose
-------
Replay the exact frozen Step 9I decision process across historical sessions, one day at a time:

1. Use only information available through the 09:40-labelled bar.
2. Assign the frozen market regime.
3. Classify all 18 holdout tickers.
4. Seal all 8 x 18 ticker-contract decisions in a separate immutable replay ledger.
5. Reveal later bars and evaluate candidates, trades, controls, comparators, and guardrails.
6. Export the regime-strategy relationship.

This replay is always labelled HISTORICAL_REPLAY_NOT_CONFIRMATORY. It never writes to the live
Step 9I prospective ledger and can never activate the router.

Run
---
From the Regime trading project root:

    .\run_step9ir_historical_replay.ps1 -StartDate "2026-05-25" -EndDate "2026-07-24"

The current Step 9I database starts around 2026-05-27, so the script automatically reports the
effective available replay start. A repeat run is idempotent. To deliberately rebuild the separate
non-confirmatory replay ledger after a code change:

    .\run_step9ir_historical_replay.ps1 -StartDate "2026-05-25" -EndDate "2026-07-24" -ResetReplay

Primary analysis outputs
------------------------
- data\step9ir_replay_regime_strategy_matrix.csv
- data\step9ir_replay_contract_performance.csv
- data\step9ir_replay_daily_regimes.csv
- data\step9ir_replay_daily_summary.csv
- data\step9ir_replay_cumulative_pnl.csv
- data\step9ir_replay_comparisons.csv
- data\step9ir_replay_ticker_performance.csv
- data\step9ir_replay_sector_performance.csv
- data\step9ir_replay_audit.csv

Immutable replay ledger
-----------------------
- data\step9ir_historical_replay_ledger.db

Interpretation
--------------
Use this replay to understand whether the chosen strategies behave differently under their locked
market regimes, how often the setups appear, and whether controls and guardrails separate outcomes.
Do not combine these rows with live prospective Step 9I evidence.
