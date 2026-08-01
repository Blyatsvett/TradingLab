V1 RESEARCH VALIDATION SUITE ROADMAP
====================================

Frozen strategy under validation:
REGIME_AWARE_GAP_RECOVERY_V1

Status
------
Step 1 - True max-two-position portfolio simulation         COMPLETE
Step 2 - Profit concentration and leave-one-out              COMPLETE
Step 3 - Execution and transaction-cost stress testing       COMPLETE
Step 4 - Parameter robustness grid                           COMPLETE
Step 5 - Nasdaq/Yahoo quality and session-completeness gates COMPLETE
Step 6 - Exposure and capital-efficiency report              COMPLETE

Validation-suite conclusion rules
---------------------------------
- V1 remains unchanged.
- Every module is research-only and shadow-only.
- Portfolio capacity is applied chronologically.
- Conservative same-timestamp handling is retained.
- New rules are not promoted from in-sample results alone.
- Incomplete current sessions are not used as final evidence.
- Provider quality is separated into trading-action agreement,
  exact diagnostic agreement, and session-completeness gates.
- Capital-efficiency metrics are kept separate from account returns.
- Mechanical annualization and linear sizing scenarios are not forecasts.

Next research phase
-------------------
Step 7 - Simple research-only improvement candidates:
- opening-range risk filter
- entry-time buckets
- gap-size buckets
- regime/sector confirmation
- forward-only comparison against frozen V1

More complete forward Nasdaq/Yahoo sessions remain necessary before any
shadow variant can be considered for promotion.
