V1 RESEARCH VALIDATION SUITE - STEP 2
=====================================

Scope
-----
Research-only profit concentration and leave-one-out validation for
REGIME_AWARE_GAP_RECOVERY_V1.

This step does not alter V1 candidate, entry, stop, target, exit, cost,
position-size, or maximum-position rules.

Method
------
All stress scenarios rerun the Step 1 chronological max-two-position portfolio.
This is important because removing a trade or group can free capacity and allow a
previously rejected signal to enter the portfolio.

Outputs
-------
data\v1_validation_concentration_summary.csv
data\v1_validation_concentration_scenarios.csv
data\v1_validation_contribution_detail.csv
data\v1_validation_leave_one_out.csv

Leave-one-out dimensions
------------------------
- ticker
- calendar month
- ISO week
- early market regime

Concentration scenarios
-----------------------
- remove top 1, 3, and 5 profitable baseline trades
- remove top 1, 3, and 5 profitable baseline days

Run only Step 2
---------------
.\run_v1_validation_step2.ps1

Run Steps 1 and 2
-----------------
.\run_v1_validation_suite.ps1

Run complete isolated workflow
------------------------------
.\run_regime_research.ps1
