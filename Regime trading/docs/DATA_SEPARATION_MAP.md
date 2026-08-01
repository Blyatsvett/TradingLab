# Data Separation Map

Status: inventory, reference mapping, rehearsal, and migration are complete for the mixed legacy regime-research families. Active runtime output and snapshot paths are centrally configurable, and the current workspace has no unclassified payload files directly under `data/`. Any newly restored payload must be classified before use.

The remaining root-level items are classified in `docs/ROOT_DATA_CLASSIFICATION_V1.md`. The current passes also centralized `data/powerbi_exports.xlsx` → `data/outputs/kpi/` and the active Step 9I/9L CSV families under `data/outputs/shadow/`.

## Inventory snapshot

The current `data/` tree contains approximately:

- 1,784 files
- 0.182 GB total
- 10 database files
- 435 CSV files
- 14 JSON files
- 3 Excel workbooks
- 1 ZIP archive
- 1,315 Nasdaq raw-data files under `nasdaq_raw/`

The flat root is a mixed historical research workspace. It contains source databases, prospective ledgers, generated research tables, KPI exports, session metadata, and old validation artifacts together.

## Proposed target layout

This is the intended layout for a later, controlled migration. It is not yet implemented.

```text
data/
  source/
    market/              # intraday and Nasdaq source/collector databases
    taxonomy/            # static and point-in-time universe inputs
  ledgers/
    prospective/        # active Step 9I/9L/9S/9R/9T/9U ledgers
    historical/         # replay and research ledgers
  outputs/
    canonical/          # stage exports and current generated CSVs
    kpi/                # Step 9KPI and Power BI feed outputs
    sessions/           # session registry, snapshots, run receipts
  archives/
    raw/                # immutable Nasdaq raw files and source archives
    freezes/            # immutable historical freeze artifacts
    legacy/             # superseded output families and packaged exports
```

The target layout deliberately separates *what a file is* from *which stage produced it*. Stage names remain in filenames and metadata so provenance is not lost.

## High-confidence classifications

### Source data

- `source/market/intraday_prices.db` — original market-data source referenced through the shared path configuration.
- `source/market/step9h_holdout_intraday_prices.db` — holdout market-data source.
- `source/market/step9i_shadow_intraday_prices.db` — current Step 9I shadow market-data input used by the V2 morning pipeline.
- `source/market/nasdaq_forward_data.db` and its `-wal`/`-shm` sidecars — Nasdaq collector database; sidecars remain paired with the database.
- `instrument_static_taxonomy.csv`, `instrument_characteristic_definitions.csv`, `instrument_point_in_time_characteristics.csv`, `instrument_group_daily_state.csv`, and relationship/coverage registries — reusable taxonomy and universe inputs.

These should move only after all producers and consumers use centralized paths. `nasdaq_raw/incoming` and `nasdaq_raw/probe` are operational raw-data areas and need a separate review from the already archived raw files.

### Prospective ledgers

The following are the current V2 ledger identities in `config/stage_registry.json` and should eventually live under `data/ledgers/prospective/`:

- `ledgers/prospective/step9i_v2_shadow_ledger.db`
- `ledgers/prospective/step9l_v3_selected_strategy_shadow_ledger.db`
- `step9s_prospective_contingency_shadow_v1.db`
- `ledgers/prospective/step9r_prospective_selector_shadow_v1.db`
- `step9t_regime_transition_archetype_prospective_v1.db`
- `step9u_contingency_selector_prospective_shadow_v1.db`

At the time of this inventory, the Step 9S, Step 9T, Step 9U, and Step 9V database files are configured destinations but are not present in the current checkout. They must not be created as placeholder files during this reorganization; the active pipeline should create them when those stages run.

These are the highest-risk files to move because the live morning wrapper, validation workflow, tests, KPI configuration, and support tooling refer to their current paths.

### Historical and research ledgers

These should be separated from prospective ledgers, but not treated as disposable:

- `step9ir_historical_replay_ledger.db`
- `step9ir_v2_historical_replay_ledger.db`
- `ledgers/research/step9r_candidate_ranking_research_v1.db`

The historical replay output families associated with Step 9IR, Step 9M, Step 9N, and Step 9O should travel with their provenance manifests if they are moved.

### Generated outputs

The following groups are generated evidence rather than primary inputs:

- root-level `step9i_v2_*` and `step9l_v3_*` CSV exports
- root-level `step9j_*`, `step9k_*`, `step9m_*`, `step9n_*`, and `step9o_*` research exports
- `outputs/research/step9r/` (moved during Phase 2)
- `outputs/observer/step9v_intraday_regime_transition_observer_v1/`
- `outputs/kpi/` output tables and workbooks (moved during Phase 2)
- root-level regime, playbook, challenger, holdout, sector, and validation CSV families
- `outputs/sessions/prospective_session_registry/` run receipts and missed-session records (moved during Phase 2)
- `step9_morning_v2_snapshots/` when present

`step9kpi/hotfix_backups/` is an exception: it is a historical backup and should not be mixed with current KPI outputs.

### Archives and immutable evidence

These should eventually be placed under archive-oriented paths, preserving their internal structure and hashes:

- `archives/raw/nasdaq_raw_archive/` (moved during Phase 1)
- `archives/freezes/step9s_historical_contingency_replay_v1/freeze_v1/`
- `archives/freezes/step9t_regime_transition_archetype_research_v1/freeze_92b274cb24cad391/`
- `archives/freezes/step9u_historical_contingency_selector_v1/freeze_8042ad803be28ccf/`
- `archives/legacy/step9u_historical_contingency_selector_v1_outputs.zip` (moved during Phase 1)
- `archives/legacy/step9kpi_hotfix_backups/` (moved during Phase 1)

Freeze manifests and source-hash files are evidence controls. They must be moved as complete units, not file-by-file.

Historical complete-case snapshots are archived under:

- `archives/research/legacy/complete_cases/step9m_complete_case_2026-05-27_to_2026-07-24/`
- `archives/research/legacy/complete_cases/step9n_complete_case_2026-05-27_to_2026-07-24/`
- `archives/research/legacy/complete_cases/step9o_complete_case_2026-05-27_to_2026-07-24/`

Additional legacy challenger research outputs are archived under:

- `archives/research/step9j_v2/`
- `archives/research/step9k/`

The mixed regime-research outputs are organized under:

- `outputs/research/legacy/regime/gap_recovery/`
- `outputs/research/legacy/regime/v1_timing/`
- `outputs/research/legacy/regime/features/`
- `outputs/research/legacy/regime/taxonomy/`
- `outputs/research/legacy/regime/playbook/`
- `outputs/research/legacy/regime/challenger/`
- `outputs/research/legacy/regime/instrument_taxonomy/`
- `outputs/research/legacy/regime/sector_strategy/`
- `outputs/research/legacy/regime/state_filtered/`
- `outputs/research/legacy/regime/holdout/`

## Reference map and migration hazards

### Active runtime references

- `RegimeTrading/core/paths.py` currently defines one `DATA_DIR`, so older and newer scripts all resolve into the same flat directory.
- `run_step9_full_live_morning_v2.ps1` directly names the active ledgers, raw Step 9I input, snapshots, and prospective session registry.
- `run_step9_morning_v2_validation.ps1` scans the whole current `data/` tree, builds isolated validation copies, and writes temporary validation data beneath its clone.
- `config/stage_registry.json` and `config/step9kpi_read_only_evaluation_v1.json` contain active ledger paths.
- `config/paths.json` now centralizes legacy output families for V1 validation, Step 9IR replay, Step 9J/K, and the mixed regime-research families. The mixed families resolve under `outputs/research/legacy/regime/`.
- Nasdaq collection code uses `source/market/nasdaq_forward_data.db`, `source/market/nasdaq_raw`, and `outputs/collector/nasdaq/` snapshots.

### Tests and documentation

Many tests and installation documents intentionally use `data/<filename>` paths. These references must be updated together with the implementation, especially the Step 9R, Step 9S, Step 9T, Step 9U, Step 9V, KPI, and morning V2 contract tests.

### Integrity and provenance controls

- `config/step9_morning_v2_runtime_manifest.json` fingerprints selected data and freeze artifacts. Any moved fingerprinted file requires a controlled manifest update.
- Historical `*_source_hashes.json` files contain relative and absolute source paths. Moving their referenced inputs without preserving or regenerating the hash record can make a valid historical replay appear invalid.
- Excel/Power BI feeds and build manifests refer to generated files under `data/outputs/kpi`, including `powerbi_exports.xlsx`.
- SQLite `-wal`, `-shm`, and journal sidecars must be handled with the database closed and moved as a unit.

## Migration gates

No file should move until all of the following are true:

1. Every active producer and consumer has been listed in a path-reference inventory.
2. Active runtime paths are centralized rather than duplicated in wrappers and tests.
3. A copy-based rehearsal passes for the V2 preflight, morning validation, KPI build, and Nasdaq collector checks.
4. Runtime and historical manifests are regenerated or explicitly preserved with documented hash changes.
5. SQLite writers are stopped and database sidecars are accounted for.
6. A reversible migration map exists, including old path, new path, classification, references, and rollback action.

Until those gates are met for each category, its existing path remains canonical. Phase 1 archive paths are now the exception and are recorded in the migration manifest.

## Copy rehearsal result

On 2026-08-01, the complete `data/` tree was copied to an isolated temporary project root and verified before cleanup:

- 1,784 source files copied to 1,784 destination files.
- 195,179,918 bytes on both sides.
- Zero missing files, extra files, or SHA-256 mismatches.
- All 10 copied SQLite databases passed `PRAGMA integrity_check`.
- Centralized data, log, snapshot, session-registry, ledger, and export paths resolved inside the copied project root.
- The temporary rehearsal root was removed after verification.

This validates the copy and path-resolution mechanics. It does not yet authorize moving the production data tree or changing the canonical physical layout.

The proposed physical migration is tracked separately in [`DATA_MIGRATION_MANIFEST_V1.md`](DATA_MIGRATION_MANIFEST_V1.md) and its machine-readable companion `config/data_migration_manifest_v1.json`.
