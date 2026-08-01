# Regime Trading Legacy File Classification

Status: first conservative documentation pass, 2026-08-01

This file records the evidence boundary used before moving historical material.
Scripts and pipelines remain in place during this pass. A filename, version
number, or `README` prefix alone is not sufficient evidence for moving an
operational file.

## Moved in this pass

The following files are historical development notes, obsolete workflow notes,
or reports with no active runtime consumer. They are moved to
`docs/legacy/regime_notes/` and remain available for provenance:

- `README.txt`
- `README_REGIME_SYSTEM_ROADMAP.txt`
- `README_REGIME_SYSTEM_STEP7.txt`
- `README_REGIME_SYSTEM_STEP7B.txt`
- `README_REGIME_SYSTEM_STEP8.txt`
- `README_REGIME_SYSTEM_STEP9A.txt`
- `README_REGIME_SYSTEM_STEP9B.txt`
- `README_REGIME_SYSTEM_STEP9C.txt`
- `README_REGIME_SYSTEM_STEP9D.txt`
- `README_REGIME_SYSTEM_STEP9E.txt`
- `README_REGIME_SYSTEM_STEP9F.txt`
- `README_REGIME_SYSTEM_STEP9G.txt`
- `README_REGIME_SYSTEM_STEP9H.txt`
- `README_REGIME_SYSTEM_STEP9I.txt`
- `README_REGIME_SYSTEM_STEP9IR.txt`
- `README_REGIME_SYSTEM_STEP9J.txt`
- `README_V1_VALIDATION_STEP6_RECONCILIATION.txt`
- `README_V1_VALIDATION_SUITE_ROADMAP.txt`
- `README_V1_VALIDATION_SUITE_STEP1.txt` through `README_V1_VALIDATION_SUITE_STEP6.txt`
- `README_NASDAQ_NO_DATA_FIX.txt`
- `README_NASDAQ_PHASE1.txt`
- `README_NASDAQ_PROBE_V2.txt` through `README_NASDAQ_PROBE_V5.txt`
- `README_STEP9A_CONTRACT_AUDIT_FIX.txt`
- `README_STEP9H_STRICT_EARLY_COMPLETENESS_FIX.txt`
- `README_STEP9I_WINDOWS_SQLITE_CLEANUP.txt`
- `README_STRATEGY_DECISION_COMPARISON.txt`
- `Regime based strategy.txt`
- `ROUTINE AND SCRIPS.txt`
- `Scripts and Routines.txt`
- `UPDATED STRATEGY ADJUSTED.txt`
- `Next steps for improving engine.txt`
- `Query to find code for 9H.txt`
- `VALIDATION_REPORT_STEP9E_SOURCE_LABEL_RELIABILITY_V1.txt`

## Retained at the project root for now

- Current V2 orchestration, collector, stage, and validation wrappers.
- Current stage contracts and install/readme files for Step 9S through Step 9V.
- `README_NASDAQ_COLLECTOR.txt` and `README_ALL23_TRADABLE_V2.txt`, which support
  current data collection and V2 research context.
- Patch manifests, build manifests, schema dictionaries, and installation
  payload metadata. These remain provenance evidence until a separate manifest
  index is prepared and every producer/consumer reference is audited.
- All Python scripts and PowerShell wrappers. Their operational status is
  documented, but they are not moved in this pass.

## Reference rule

The canonical current guides are `docs/ACTIVE_SYSTEM_GUIDE.md` and
`docs/REPRODUCIBILITY.md`. Historical references to the old root paths are
preserved inside manifests as provenance strings; active documentation points
to the new `docs/legacy/regime_notes/` location.
