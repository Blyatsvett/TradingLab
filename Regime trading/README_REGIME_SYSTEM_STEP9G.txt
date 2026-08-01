STEP 9G - PRE-REGISTERED STATE-FILTERED CONTRACT EXPERIMENTS
============================================================

Purpose
-------
Step 9G converts selected Step 9F discoveries into fixed, point-in-time-safe
strategy contracts and reruns them from raw five-minute bars on their eligible
pre-entry cohorts.

It does not subset the previously profitable Step 9D trades. State eligibility
is applied first, the strategy ranks and selects within that filtered cohort,
and execution is then simulated from 09:45 onward.

This remains simulation-only discovery research. No strategy is optimized,
promoted, or activated in the router.

Pre-registered experiment family
--------------------------------
Seven primary hypotheses are paired with seven explicit complement controls:

1. TREND_UP + EARLY_LEADER -> range rejection
   Complement: TREND_UP + EARLY_LAGGARD
2. VOLATILITY_EXPANSION + ALIGNED_WITH_GROUP -> early continuation
   Complement: CONTRARIAN_TO_GROUP
3. VOLATILITY_EXPANSION + ALIGNED_WITH_GROUP -> close-confirmed ORB
   Complement: CONTRARIAN_TO_GROUP
4. HIGH_DISPERSION + EARLY_LAGGARD -> early continuation
   Complement: EARLY_LEADER
5. HIGH_DISPERSION + EARLY_LAGGARD -> delayed reversal
   Complement: EARLY_LEADER
6. RANGE_LOW_VOL + EARLY_LAGGARD + HIGH_RELATIVE_VOL -> delayed reversal
   Complement: EARLY_LAGGARD without high relative volatility
7. RANGE_LOW_VOL + CONTRARIAN_TO_GROUP -> range rejection
   Complement: ALIGNED_WITH_GROUP

Same-cohort strategy comparisons
--------------------------------
The following competing strategies receive identical pre-entry cohorts:

- VOLATILITY_EXPANSION + ALIGNED_WITH_GROUP:
  early continuation versus close-confirmed ORB
- HIGH_DISPERSION + EARLY_LAGGARD:
  early continuation versus delayed reversal
- HIGH_DISPERSION + EARLY_LEADER control:
  early continuation versus delayed reversal

Statistical and robustness diagnostics
--------------------------------------
- Date-level bootstrap 95% intervals
- One-sided date-level sign-flip tests
- Benjamini-Hochberg adjustment across the seven primary hypotheses
- Leave-one-day-out, leave-one-company-out, and leave-one-sector-out results
- Equal-notional and fixed-risk-capped P&L
- Exact trade-to-leg reconciliation
- Point-in-time and execution-invariant audits

These diagnostics remain discovery evidence. Statistical screening never
promotes a strategy in Step 9G.

Run
---
From the project root:

    .\run_step9g_state_filtered_contract_experiments.ps1

Or run the complete workflow:

    .\run_regime_research.ps1

Outputs
-------
- data\regime_state_filtered_summary.csv
- data\regime_state_filtered_contract_registry.csv
- data\regime_state_filtered_session_coverage.csv
- data\regime_state_filtered_candidates.csv
- data\regime_state_filtered_trades.csv
- data\regime_state_filtered_trade_legs.csv
- data\regime_state_filtered_performance.csv
- data\regime_state_filtered_same_cohort_comparisons.csv
- data\regime_state_filtered_robustness.csv
- data\regime_state_filtered_multiple_testing.csv
- data\regime_state_filtered_audit.csv

Expected mechanical classification
----------------------------------
STATE_FILTERED_CONTRACT_EXPERIMENT_READY_FOR_CONTROLLED_REVIEW
