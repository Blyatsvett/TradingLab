# Step 9T Historical Replay V1 Installation

This patch adds a read-only historical research layer only. It does not modify
Step 9I, Step 9L, Step 9Q, Step 9R, Step 9S, ORB, or any existing ledger.

Required local diagnostic input:

`data/july28_ticker_market_performance.csv`

The file was generated read-only from the July 28 Step 9I price database and is
used only to reconcile the historical case study.

After installation:

1. Run the dedicated Step 9T tests.
2. Run `tools/verify_step9t_historical_replay_v1.py`.
3. Move any old Step 9T output directory outside the project.
4. Run `run_step9t_historical_replay_v1.ps1`.
5. Run the complete project test suite.

Expected current-project totals:

- 62 sessions
- 9 opening regimes
- 1,798 ticker-archetype rows
- 1,798 ticker-outcome rows
- July 28 opening regime `TREND_DOWN`
- July 28 09:50 transition `WEAKNESS_PERSISTING`
- 266 project tests

The standardized historical P&L is diagnostic only and must not be interpreted
as prospective performance.
