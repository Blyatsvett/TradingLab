V1 RESEARCH VALIDATION SUITE - STEP 5
=====================================

Purpose
-------
Validate whether Nasdaq and Yahoo provide sufficiently complete and aligned
five-minute data for independent shadow verification of
REGIME_AWARE_GAP_RECOVERY_V1.

This module does not change V1 and does not make Nasdaq a strategy input.

Inputs
------
data/nasdaq_yahoo_strategy_decision_comparison.csv
data/nasdaq_yahoo_bar_comparison.csv

Outputs
-------
data/v1_validation_provider_quality_summary.csv
data/v1_validation_provider_session_detail.csv
data/v1_validation_provider_daily_summary.csv
data/v1_validation_provider_mismatch_detail.csv

Completeness stages
-------------------
LIVE_SETUP_READY
    Both providers contain the 09:30 opening bar, sufficient regime-window
    coverage, and the 09:45 cutoff bar.

FINAL_TRIGGER_READY
    The live-setup gate passes and both providers have at least 95 percent
    entry-window coverage plus the 13:00 bar.

FINAL_OUTCOME_READY
    The final-trigger gate passes and both providers have at least 95 percent
    09:30-16:30 coverage plus the 16:30 bar.

INCOMPLETE
    One or both providers have not passed the applicable completeness gate.

Match metrics
-------------
Trading-action match
    Compares the operational action: invalid/no trade, waiting, no entry yet,
    or entry triggered. Different diagnostic reason labels do not reduce this
    metric when the actual action is unchanged.

Exact diagnostic match
    Preserves the previous strict comparison, including invalid-reason labels,
    price levels, trigger state, and available outcome details.

Quality thresholds
------------------
Stage-appropriate provider overlap: at least 95 percent.
Stage-appropriate OHLC agreement: at least 95 percent of overlapping bars
within one basis point.

Commands
--------
Run Step 5 only:
    .\run_v1_validation_step5.ps1

Run all validation steps:
    .\run_v1_validation_suite.ps1

The Nasdaq collection and strategy-decision comparison launchers now run Step
5 automatically after refreshing their source comparison files.
