STEP 9H STRICT EARLY COMPLETENESS AND AUDIT FIX

Purpose
- Require the exact 09:30, 09:35 and 09:40 five-minute bars for every ticker-day used by a Step 9H contract.
- Rebuild sector/group direction using only those complete ticker-days.
- Distinguish missing early data from actual point-in-time leakage.
- Preserve the locked holdout universe, contracts, execution parameters, thresholds and zero-promotion policy.

Files changed
- RegimeTrading/scripts/step9h_cross_sectional_holdout_transport.py
- tests/test_step9h_cross_sectional_holdout_transport.py

Expected test result
- Ran 111 tests
- OK

After extracting, rerun only:
  .\run_step9h_cross_sectional_holdout_transport.ps1

No new Yahoo download is required.
