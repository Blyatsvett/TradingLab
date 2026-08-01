# Install Step 9S Historical Contingency Replay V1

This patch adds a research-only historical replay. It does not modify existing engine files or databases.

Files added:

- `RegimeTrading/scripts/step9s_historical_contingency_replay_v1.py`
- `tests/test_step9s_historical_contingency_replay_v1.py`
- `config/step9s_historical_contingency_replay_v1.json`
- `run_step9s_historical_contingency_replay_v1.ps1`
- `STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1_README.md`

The replay writes only new output files below:

- `data/step9s_historical_contingency_replay_v1/`

It reads existing research data and `intraday_prices.db` read-only. It does not read or write the Step 9I or Step 9L ledgers and sends no orders.
