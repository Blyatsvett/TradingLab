V1 RESEARCH VALIDATION SUITE - STEP 3
=====================================

Purpose
-------
Stress-test REGIME_AWARE_GAP_RECOVERY_V1 under more conservative execution
and transaction-cost assumptions without changing V1 trade selection, entry
or exit timestamps, stop/target rules, or max-two-position portfolio logic.

Run
---
Full research workflow:
    .\run_regime_research.ps1

Validation suite steps 1-3 only:
    .\run_v1_validation_suite.ps1

Step 3 only:
    .\run_v1_validation_step3.ps1

Outputs
-------
- data\v1_validation_execution_stress_summary.csv
- data\v1_validation_execution_stress_scenarios.csv
- data\v1_validation_execution_stress_trade_detail.csv
- data\v1_validation_execution_cost_curve.csv

Stress assumptions
------------------
- Baseline V1 total cost is 5 basis points per completed trade.
- Entry slippage is adverse: stressed entry price is higher for long trades.
- STOP_HIT and CLOSED_EOD are treated as market-like exits and can receive
  adverse exit slippage.
- TARGET_HIT is treated as a limit-price fill and receives no exit slippage in
  the predefined scenarios.
- Open trades retain zero realized PnL.
- Position selection and capacity are re-simulated with the frozen Step 1
  chronological max-two-position model.

Important limitation
--------------------
Five-minute OHLC bars cannot reveal actual queue position, spread, order-book
liquidity, or within-bar stop slippage. The scenarios are deterministic stress
tests, not claims about actual historical fills.

Interpretation
--------------
Step 3 measures the execution margin of safety. It does not authorize a V1 rule
change. Parameter changes belong in later shadow variants and robustness tests.
