STEP 9A - EXECUTABLE PLAYBOOK SPECIFICATIONS AND DATA READINESS
================================================================

Purpose
-------
Turn every provisional Step 8 regime response into an explicit, versioned,
point-in-time-safe simulation contract before any cross-regime performance
comparison is run.

This step does not claim that any new playbook is profitable or validated.
It defines deterministic baseline basket, signal, entry, stop, target, time-exit,
cost, sizing, and data-readiness rules for later simulation.

Key principles
--------------
- Simulation only. No live orders or money are involved.
- Every Step 8 regime has an active response.
- Frozen legacy V1 remains router-ineligible.
- RECOVERY uses STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH.
- Current-data proxies are documented rather than hidden.
- Missing optional data is not silently treated as available.

Run
---
.\run_step9_playbook_specifications.ps1

Outputs
-------
data\regime_playbook_specification_summary.csv
data\regime_playbook_registry.csv
data\regime_playbook_data_requirements.csv
data\regime_playbook_session_coverage.csv

Next step
---------
Step 9B/10 implements the baseline trade-generation and shared-portfolio
simulation engine from these contracts, then compares playbook performance by
regime without selecting winners from the same sample.
