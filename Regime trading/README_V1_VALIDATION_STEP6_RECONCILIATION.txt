V1 VALIDATION SUITE - STEP 6 RECONCILIATION GATE
=================================================

Purpose
-------
Ensure the Step 6 exposure/capital-efficiency report uses exactly the same
selected trades and realized PnL as the Step 1 max-two-position portfolio
simulation generated in the current workflow run.

Checks
------
- Step 1 portfolio summary PnL
- Sum of Step 1 closed-trade ledger PnL
- Final Step 1 equity-curve PnL
- Step 6 summary PnL
- Sum of Step 6 position-detail PnL
- Sum of Step 6 daily PnL
- Current-V1 position-size scenario PnL
- Closed/open position counts
- Missing, extra, and duplicate source trade IDs

The workflow stops with a non-zero exit code if any check fails.

New output
----------
data\v1_validation_exposure_reconciliation.csv

Interpretation
--------------
PASS_EXACT_SAME_RUN_RECONCILIATION means Step 1 and Step 6 agree exactly for
the current files. A different PnL printed in an earlier workflow log then
reflects a different underlying data snapshot/run, not a Step 6 omission.
