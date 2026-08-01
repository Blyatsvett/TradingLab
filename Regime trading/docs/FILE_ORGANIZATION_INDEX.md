# Regime Trading - File Organization Index

Status: conservative reorganization  
Last reviewed: 2026-08-01

This index records what may be treated as current, what is clearly historical, and what remains intentionally unresolved. A file is not classified as historical merely because it has an older version number.

## Current entry-point candidates

These are the current V2 morning orchestration and reporting entry points identified by the active-system audit:

- `run_step9_full_live_morning_v2.ps1`
- `run_step9_full_tonight_preflight_v2.ps1`
- `run_step9_morning_v2_validation.ps1`
- `run_step9_morning_mock_fallback_v2.ps1`
- `register_step9_morning_v2_tasks.ps1`
- `run_step9i_v2_morning_shadow_router.ps1`
- `run_step9i_v2_eod_shadow_evaluator.ps1`
- `run_step9l_v3_morning_research_engine.ps1`
- `run_step9l_v3_eod_research_engine.ps1`
- `run_step9s_prospective_morning.ps1`
- `run_step9s_prospective_eod.ps1`
- `run_step9r_v1_prospective_shadow.ps1`
- `run_step9r_v1_eod_shadow.ps1`
- `run_step9t_prospective_snapshot_v1.ps1`
- `run_step9t_prospective_eod_v1.ps1`
- `run_step9t_prospective_audit_v1.ps1`
- `run_step9u_prospective_selection_v1.ps1`
- `run_step9u_prospective_eod_v1.ps1`
- `run_step9u_prospective_audit_v1.ps1`
- `run_step9v_checkpoint_v1.ps1`
- `run_step9v_eod_v1.ps1`
- `run_step9v_audit_v1.ps1`
- `run_step9q_powerbi_snapshot.ps1`
- `run_step9kpi_read_only_evaluation_v1.ps1`

These files remain in the project root because many wrappers use `$PSScriptRoot` and relative paths. They should not be moved until their path assumptions are tested.

## Current source candidates

The current research/shadow source modules are under:

- `RegimeTrading/core/`
- `RegimeTrading/scripts/`
- `tools/`
- `tests/`

The canonical stage chain is documented in `ACTIVE_SYSTEM_GUIDE.md`.

## Clearly historical material

The following material is separated from the active root or clearly marked as historical:

- `backups/`
- `Regime trading mock sessions/`
- `Zip bod installation/`
- `backups/entrypoint-archives/20260729/`

The `entrypoint-archives` folder contains six unreferenced, explicitly named V1 backup copies moved during the 2026-08-01 cleanup. No active wrapper depends on them by filename.

Historical root-level development notes and old research reports are now
under `docs/legacy/regime_notes/`. See `docs/LEGACY_FILE_CLASSIFICATION.md`
for the exact moved set and the retained root-level evidence.

## Legacy but not yet moved

These are likely historical or superseded, but remain in place until execution references are fully verified:

- V1 `step9tu` morning wrappers.
- Original `run_regime_research.ps1` and `run_research_only.ps1` gap-recovery workflow.
- Older Step 9I and Step 9L wrapper variants.
- Step 7 through Step 9 development/research wrappers.
- Patch manifests, hotfix notes, and installation notes in the project root.

Their presence does not mean they are part of the daily canonical chain. They remain available because they may be needed to reproduce historical research.

## Data organization status

The active data tree is now separated into:

- `data/source/` for raw market data and reusable references
- `data/ledgers/` for prospective and research databases
- `data/outputs/` for generated reports, shadow outputs, collectors, and observers
- `data/archives/` for frozen and historical evidence

The remaining work is documentation cleanup and classification of any new
payload restored from another machine. Do not introduce files directly under
`data/`.

## Reorganization rules

1. Do not move a script solely because its name contains `v1`, `research`, `test`, or `step9`.
2. Before moving an operational candidate, search wrappers, tests, scheduled-task definitions, docs, and generated manifests for path references.
3. Preserve historical copies before changing a path.
4. Prefer updating one path abstraction over editing many scripts with string replacements.
5. After each move, run PowerShell parser checks, Python compilation, focused tests, and a dry-run/status check.
6. Never move or rewrite prospective ledgers as part of source organization.
