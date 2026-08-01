# Regime Trading - Active System Guide

Status: research and shadow operation only  
Last audited: 2026-08-01  
Project root: `TradingLab/Regime trading`

This document identifies the current Regime Trading system, its approved entry points, data flow, evidence boundaries, and historical material. It is the starting point for future maintenance and refactoring.

For setup, canonical commands, validation, and data restoration, use `docs/REPRODUCIBILITY.md`.

## Current scope

Regime Trading is currently a research/backtesting and prospective-shadow project. It does not place broker orders or manage live capital.

The separate `TradingLab/Intraday` project contains the frozen ORB paper/production workflow and must not be changed from this project.

## Canonical pipeline

```text
Market data collection
        |
Step 9I V2 - broad baseline shadow engine
        |
Step 9L V3 - selected-strategy shadow engine
        |
Step 9S - contingency coverage and mandatory control
        |
Step 9R - candidate ranking / zero-to-two research
        |
Step 9T - regime transition and archetype observer
        |
Step 9U - contingency selector / challenger portfolio
        |
Step 9V - intraday transition observer
        |
Step 9Q - Power BI reporting feed
        |
Step 9KPI - read-only evaluation
```

Step 9R is a research layer and is not allowed to block the critical morning stages. Step 9V observes counterfactual actions; it does not modify the Step 9U portfolio.

## Approved current entry points

### Morning orchestration

| Purpose | Entry point |
|---|---|
| Full morning run | `run_step9_full_live_morning_v2.ps1` |
| Evening preflight | `run_step9_full_tonight_preflight_v2.ps1` |
| V2 lifecycle validation | `run_step9_morning_v2_validation.ps1` |
| Isolated mock fallback | `run_step9_morning_mock_fallback_v2.ps1` |
| Scheduled-task registration | `register_step9_morning_v2_tasks.ps1` |

The V2 orchestrator delegates to:

- `RegimeTrading.scripts.step9_morning_v2_stage_runner`
- `RegimeTrading.scripts.step9_morning_v2_persistent_worker`
- `tools/step9_morning_v2_support.py`
- `tools/step9_morning_v2_exit_code.ps1`

### Stage wrappers

| Stage | Research/shadow wrapper family |
|---|---|
| Data | `collect_step9i_v2_shadow_data.ps1` |
| 9I V2 | `run_step9i_v2_morning_shadow_router.ps1`, `run_step9i_v2_eod_shadow_evaluator.ps1` |
| 9L V3 | `run_step9l_v3_morning_research_engine.ps1`, `run_step9l_v3_eod_research_engine.ps1` |
| 9S | `run_step9s_prospective_morning.ps1`, `run_step9s_prospective_eod.ps1` |
| 9R | `run_step9r_v1_prospective_shadow.ps1`, `run_step9r_v1_eod_shadow.ps1` |
| 9T | `run_step9t_prospective_snapshot_v1.ps1`, `run_step9t_prospective_eod_v1.ps1`, `run_step9t_prospective_audit_v1.ps1` |
| 9U | `run_step9u_prospective_selection_v1.ps1`, `run_step9u_prospective_eod_v1.ps1`, `run_step9u_prospective_audit_v1.ps1` |
| 9V | `run_step9v_checkpoint_v1.ps1`, `run_step9v_eod_v1.ps1`, `run_step9v_audit_v1.ps1` |
| 9Q | `run_step9q_powerbi_snapshot.ps1` |
| KPI | `run_step9kpi_read_only_evaluation_v1.ps1` |

Inspect a wrapper’s current parameters before running it. Use explicit session dates for historical or mock work.

## Source package

Reusable Python code lives under `RegimeTrading/`:

- `RegimeTrading/core/` — paths, database access, shared research utilities, and configuration.
- `RegimeTrading/scripts/` — stage implementations, collectors, research engines, observers, exports, and validators.

The project currently contains many historical research modules. A module being present in `RegimeTrading/scripts/` does not automatically make it part of the daily canonical chain.

## Centralized paths

Python path resolution is centralized in `RegimeTrading/core/paths.py` and configured by `config/paths.json`. Relative paths resolve from the Regime Trading project root, so the project can be copied to another machine or isolated mock root without editing source files.

Supported environment overrides are:

- `REGIME_TRADING_DATA_DIR`
- `REGIME_TRADING_LOG_DIR`
- `REGIME_TRADING_SOURCE_INTRADAY_DB`
- `REGIME_TRADING_SOURCE_DB` (legacy compatibility name)
- `REGIME_TRADING_REFERENCE_MOCK_ROOT` for V2 preflight and validation

The same `config/paths.json` also defines the active snapshot, prospective-session registry, KPI, Power BI, validation, and Nasdaq raw-data roots. Stage export directories are defined in `config/stage_registry.json` and loaded through `RegimeTrading/core/stage_registry.py`.

Explicit command-line or PowerShell parameters still take precedence over environment defaults.

## Centralized stage and ledger registry

The active stage order, stage groups, and prospective ledger filenames are maintained in `config/stage_registry.json`. Python consumers load it through `RegimeTrading/core/stage_registry.py`; the V2 validation script reads the same registry directly.

The registry is descriptive only: `orders_enabled` and `router_active` remain `false`. It centralizes identity and scheduling classification without promoting any research stage or changing the live-trading boundary.

## Data and ledger boundaries

The `data/` directory currently contains both source data and generated research artifacts. Important prospective ledgers include:

- `data/ledgers/prospective/step9i_v2_shadow_ledger.db`
- `data/ledgers/prospective/step9l_v3_selected_strategy_shadow_ledger.db`
- `step9s_prospective_contingency_shadow_v1.db`
- `step9r_prospective_selector_shadow_v1.db`
- `step9t_regime_transition_archetype_prospective_v1.db`
- `step9u_contingency_selector_prospective_shadow_v1.db`

Primary market-data stores include:

- `data/source/market/step9i_shadow_intraday_prices.db`
- `step9h_holdout_intraday_prices.db`
- `intraday_prices.db`
- Nasdaq/Yahoo comparison databases and exports

Generated CSVs, audit tables, Power BI workbooks, and freeze manifests are evidence artifacts. They are not interchangeable with source data or prospective ledgers.

## Evidence rules

- Current source, ledgers, hashes, tests, and reproduced outputs outrank old installer bundles or narrative claims.
- Research and shadow stages remain inactive unless explicitly promoted in a future project phase.
- No broker orders are sent.
- Existing sealed prospective records are immutable.
- Never rerun a sealed upstream stage because a downstream stage failed.
- Keep prospective, partial-prospective, mock, and historical evidence separate.
- Never merge mock ledgers into real prospective ledgers.
- Never fabricate missing market bars to satisfy completeness checks.
- Step 9S natural results may overlap Step 9L and must not be double-counted.
- Step 9V recommendations are observer counterfactuals and do not alter Step 9U holdings.

## Current versus historical material

### Current candidates

- V2 morning orchestrator and its support modules.
- Step 9I V2, Step 9L V3, Step 9S, Step 9R, Step 9T, Step 9U, Step 9V, Step 9Q, and Step 9KPI modules.
- The current project `tests/` and `tools/` directories.
- Current prospective ledgers, configs, and freeze manifests.

### Historical or parallel material

- `backups/`
- `Regime trading mock sessions/`
- `Zip bod installation/`
- V1 `step9tu` morning wrappers.
- Older Step 9I/9L variants and superseded research engines.
- Step 7–9 development experiments and old patch manifests.
- The original root workflow described by `docs/legacy/regime_notes/README.txt`, which covers the earlier gap-recovery project.

Historical material is retained for reproducibility. Do not delete or rewrite it during normal development.

## Consolidated note index

Older Regime Trading notes remain available as provenance, but the following rules now govern their use:

The historical development notes listed below now live under
`docs/legacy/regime_notes/`. Their original filenames are preserved there;
patch manifests may still mention the original names as historical provenance.

- `README_REGIME_SYSTEM_ROADMAP.txt` and the Step 7–9 README files describe development history; the canonical current chain is the pipeline documented above.
- `ROUTINE AND SCRIPS.txt`, `Scripts and Routines.txt`, and `UPDATED STRATEGY ADJUSTED.txt` are historical operating notes; use the approved entry-point table and `docs/REPRODUCIBILITY.md` for current commands.
- `PATCH_MANIFEST*`, `INSTALL_*`, and `STEP9*_PATCH_MANIFEST*` files are installation/provenance evidence. They do not override the current configuration or path registry.
- Step 9R/9S/9T/9U/9V README and specification files remain the detailed stage contracts; their active status is governed by the current configs, ledgers, hashes, and tests.
- Screenshots under `prt screens/`, frozen material under `backups/`, and installer material under `Zip bod installation/` support historical interpretation only.

When an older note conflicts with current code, the precedence order is: current source and tests, current config/registry, current manifests and ledgers, then historical notes and installer bundles.

## Verification baseline

The dependency-free canonical contract check is `tools/validate_canonical_pipeline.py`. It verifies the stage order, centralized data boundaries, required current entry points, and the research-only execution flags before third-party packages or local market data are needed. The Codex-bundled Python runtime does not include SciPy or pytest and is suitable only for static checks.

The current project test collection contains 395 tests; the complete collection
passed in bounded batches on 2026-08-01.

The active project currently has approximately 50 Python test files and 389 test functions by source inspection. The primary Python source compiles successfully, and the main V2 PowerShell entry points pass parser validation. The project-local `.venv` must contain NumPy, Pandas, SciPy, OpenPyXL, pytest, and yfinance; run `tools/check_dependencies.py` before treating missing verifier output as a code failure. The Codex-bundled Python runtime does not include SciPy and is suitable only for static checks unless separately provisioned.

The project’s local `.venv` is the intended test environment. If it cannot be launched, resolve the environment issue before treating missing pytest output as a code failure.

## Safe next refactoring sequence

1. Make the V2 orchestrator and canonical stages the only documented “current” path.
2. Split `data/` conceptually into source data, ledgers, outputs, and archives without moving files yet.
3. Record the active test command and environment setup.
4. Remove hard-coded machine-specific paths from active wrappers through configuration. **Completed.**
5. Centralize stage groups and ledger filenames in `config/stage_registry.json`. **Completed.**
6. Move or rename historical wrappers only after their references and reproducibility value are recorded.
7. Refactor shared Python utilities only after the current pipeline has a passing baseline.
