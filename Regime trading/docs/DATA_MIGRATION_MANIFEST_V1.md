# Data Migration Manifest V1

Status: Phase 13 completed. Phase 8 covered V1 validation, Step 9IR/9J/9K output families, and mixed regime-research outputs. Phase 9 centralized the Power BI workbook; Phase 10 centralized active Step 9I/9L shadow CSV outputs; Phase 11 centralized Step 9R databases; Phase 12 centralized Step 9S/9T/9U/9V outputs; Phase 13 centralized remaining source/reference data, Nasdaq assets, Step 9M/N/O outputs, and the Step 9T reconciliation input.

See `docs/ROOT_DATA_CLASSIFICATION_V1.md` for the root-level classification map.

The machine-readable source of truth is `config/data_migration_manifest_v1.json`. This document summarizes the intended sequence.

## Phase 1 completed

The only current low-risk candidates are historical archives:

- `data/archives/legacy/step9u_historical_contingency_selector_v1_outputs.zip`
- `data/archives/legacy/step9kpi_hotfix_backups/`
- `data/archives/raw/nasdaq_raw_archive/`

The ZIP had no active code reference. The KPI backup directory had documentation-only references. The Nasdaq archive had a collector documentation pattern, which has been updated to the new location.

The Step 9R output directory, KPI output directory, and prospective session registry have now been migrated under `data/outputs/`.

The approved Phase 3 database units have now been migrated:

- `data/source/market/step9i_shadow_intraday_prices.db`
- `data/ledgers/prospective/step9i_v2_shadow_ledger.db`
- `data/ledgers/prospective/step9l_v3_selected_strategy_shadow_ledger.db`

The deferred freeze directories have now been migrated as complete immutable units:

- `data/archives/freezes/step9s_historical_contingency_replay_v1/freeze_v1/`
- `data/archives/freezes/step9t_regime_transition_archetype_research_v1/freeze_92b274cb24cad391/`
- `data/archives/freezes/step9u_historical_contingency_selector_v1/freeze_8042ad803be28ccf/`

The first conservative lower-confidence legacy/research batch is also complete:

- `data/archives/research/legacy/complete_cases/step9m_complete_case_2026-05-27_to_2026-07-24/`
- `data/archives/research/legacy/complete_cases/step9n_complete_case_2026-05-27_to_2026-07-24/`
- `data/archives/research/legacy/complete_cases/step9o_complete_case_2026-05-27_to_2026-07-24/`

The centralized V1 validation and Step 9IR output families have now been migrated:

- `data/outputs/research/legacy/v1_validation/`
- `data/archives/research/step9ir_v1/`
- `data/archives/research/step9ir_v2/`

Step 9J V2 and Step 9K research outputs have also been migrated:

- `data/archives/research/step9j_v2/`
- `data/archives/research/step9k/`

The mixed regime-research output families have also been migrated after a producer/consumer audit and hash-verified copy rehearsal:

- `data/outputs/research/legacy/regime/gap_recovery/`
- `data/outputs/research/legacy/regime/v1_timing/`
- `data/outputs/research/legacy/regime/features/`
- `data/outputs/research/legacy/regime/taxonomy/`
- `data/outputs/research/legacy/regime/playbook/`
- `data/outputs/research/legacy/regime/challenger/`
- `data/outputs/research/legacy/regime/instrument_taxonomy/`
- `data/outputs/research/legacy/regime/sector_strategy/`
- `data/outputs/research/legacy/regime/state_filtered/`
- `data/outputs/research/legacy/regime/holdout/`

## Explicitly deferred

The Step 9S, Step 9T, and Step 9U freeze directories have completed their reference-preserving migration. Their contents and internal hashes were not changed; historical source-hash payloads retain their original provenance strings.

The remaining active source databases and prospective ledgers are deferred. They require the active V2 wrapper, registry, KPI configuration, tests, manifests, and any SQLite sidecars to be updated together.

Other mixed `regime_*`, taxonomy, and older pipeline outputs remain in place until their producing scripts and shared consumers receive centralized output paths.

The V1 validation and Step 9IR output paths are centralized in `config/paths.json` and now point to their organized destinations.

## Rollback rule

Every move must be performed as a complete directory or database unit, recorded in the manifest, and followed by runtime-manifest, preflight, validation, and KPI checks. The original path remains the rollback location until the phase is accepted.
