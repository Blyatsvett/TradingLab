V1 RESEARCH VALIDATION SUITE - STEP 1
=====================================

Purpose
-------
Build a chronological portfolio simulation for REGIME_AWARE_GAP_RECOVERY_V1
without changing the strategy or its source trade calculations.

Frozen assumptions used
-----------------------
- Initial capital: 10,000 SEK
- Fixed position size: 10% of initial capital = 1,000 SEK
- Maximum simultaneous positions: 2
- V1 net pnl_pct is reused and is not charged a second transaction cost
- Entry priority: entry timestamp, then ticker ascending
- Conservative same-timestamp capacity rule: entries are handled before exits

Why the same-timestamp rule matters
-----------------------------------
Five-minute bars do not reveal whether an exit happened before another entry
inside the same bar. The portfolio therefore does not reuse an exiting slot at
the exact same timestamp. This avoids optimistic intrabar ordering.

If more simultaneous signals exist than available slots, ticker ascending is a
transparent deterministic tie-break. Such groups are flagged as
capacity_ambiguous so they can be stress-tested later.

Outputs
-------
data\v1_validation_portfolio_summary.csv
data\v1_validation_portfolio_trade_ledger.csv
data\v1_validation_portfolio_equity_curve.csv
data\v1_validation_portfolio_daily.csv

Run only Step 1
---------------
.\run_v1_validation_step1.ps1

Run the full isolated workflow
------------------------------
.\run_regime_research.ps1

The full workflow runs V1 first, then this validation model, then exports and
validates the Power BI workbook.

Optional unit tests
-------------------
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
