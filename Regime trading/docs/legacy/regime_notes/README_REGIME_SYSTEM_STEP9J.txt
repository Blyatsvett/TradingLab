STEP 9J — CHALLENGER REGIME-STRATEGY REDESIGN V1
=================================================

Purpose
-------
Step 9J is a separate, post-hoc challenger branch. It diagnoses the locked Step 9I trades and tests fixed redesign contracts without changing Step 9I, the live shadow ledger, or production ORB logic.

Research status
---------------
SIMULATION_ONLY_POST_HOC_REDESIGN_DISCOVERY_NOT_CONFIRMATORY

The complete May-July replay was already viewed before these redesigns were specified. Therefore chronological halves and all statistics are descriptive discovery evidence only. No Step 9J result can promote or activate a strategy.

Locked redesign themes
----------------------
1. TREND_UP
   - aligned early-leader close-confirmed ORB
   - aligned early-leader breakout/pullback/hold continuation
   - frozen range-rejection reference

2. VOLATILITY_EXPANSION
   - aligned close-confirmed ORB primary
   - aligned early-continuation execution reference
   - contrarian close-confirmed ORB control

3. RANGE_LOW_VOL
   - all early-laggard delayed reversal
   - high-relative-volatility reference
   - low/medium-relative-volatility control
   - contrarian-to-group laggard reversal
   - aligned-with-group laggard control

Run
---
cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"

.\run_step9j_challenger_regime_strategy_redesign.ps1 `
    -StartDate "2026-05-25" `
    -EndDate "2026-07-24"

Main outputs
------------
data\step9j_challenger_performance.csv
data\step9j_challenger_comparisons.csv
data\step9j_trade_diagnostics.csv
data\step9j_time_split_performance.csv
data\step9j_ticker_performance.csv
data\step9j_sector_performance.csv
data\step9j_challenger_robustness.csv
data\step9j_challenger_multiple_testing.csv
data\step9j_challenger_audit.csv
data\step9j_summary.csv

Diagnostics
-----------
The trade diagnostics include entry time, entry bucket, opening-range width, initial move, entry extension, MFE, MAE, MFE/MAE in R, exit reason, state, alignment, and realized P&L for both:
- LOCKED_STEP9I_REFERENCE
- STEP9J_CHALLENGER

Interpretation guardrails
-------------------------
- Step 9I stays frozen.
- Step 9J is not confirmatory.
- Same-period improvement is hypothesis generation, not validation.
- No result auto-promotes.
- Selected redesigns must later receive their own prospective shadow test.
