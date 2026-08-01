V1 RESEARCH VALIDATION SUITE - STEP 4
=====================================

Purpose
-------
Test whether REGIME_AWARE_GAP_RECOVERY_V1 remains profitable under nearby
parameter choices rather than relying on one isolated combination.

The module is research-only. It does not modify V1, production ORB, paper
trading, the Nasdaq collector, or existing strategy output files.

Analysis design
---------------
- Completed sessions only. A date is included only when all 11 research
  tickers have bars through 16:30.
- V1 early-market regime definition remains fixed.
- Shared V1 execution engine, STOP same-bar priority, EOD 16:30.
- Existing 5 bps cost assumption remains fixed.
- Max-two-position portfolio simulation is rerun for every scenario.

Scenarios
---------
1 baseline scenario
17 one-at-a-time scenarios
216 controlled core-neighborhood combinations
234 rows total

Parameters tested
-----------------
- Negative-gap lower bound
- Negative-gap upper bound
- Opening-range length
- Entry-window cutoff
- Target recovery fraction
- Maximum risk percentage

Run
---
.\run_v1_validation_step4.ps1

Or run the full research workflow:
.\run_regime_research.ps1

Outputs
-------
data\v1_validation_parameter_robustness_summary.csv
data\v1_validation_parameter_robustness_scenarios.csv
data\v1_validation_parameter_sensitivity.csv
data\v1_validation_parameter_baseline_reconciliation.csv
