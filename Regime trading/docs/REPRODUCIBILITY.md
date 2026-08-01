# Regime Trading Reproducibility Runbook

This project is currently research/backtesting and prospective-shadow only. The commands below do not enable broker orders or promote a research stage to live trading.

## First-time setup

From the `Regime trading` folder in PowerShell:

```powershell
Set-Location "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
.\setup_regime_trading.ps1
```

Setup creates or reuses the project-local `.venv` and installs `requirements.txt`. The dependency check includes SciPy because Step 9R imports `scipy.stats.spearmanr`, and the Step 9H/9I collectors require SciPy when using `yfinance[repair]`.

The Codex-bundled Python runtime is useful for static checks but is not the project runtime; it does not include SciPy. Use `Regime trading\.venv\Scripts\python.exe` for project tests and verifiers.

## Canonical entry points

| Purpose | Command |
|---|---|
| Daily research workflow | `.\run_regime_research.ps1` |
| Research-only sync and gap recovery | `.\run_research_only.ps1` |
| Full evening preflight | `.\run_step9_full_tonight_preflight_v2.ps1` |
| Full morning V2 orchestrator | `.\run_step9_full_live_morning_v2.ps1` |
| Isolated morning validation | `.\run_step9_morning_v2_validation.ps1` |
| Mock fallback, explicitly isolated | `.\run_step9_morning_mock_fallback_v2.ps1` |
| Nasdaq forward-data collection | `.\run_nasdaq_collection.ps1` |

Inspect a wrapper's parameters and current data readiness before running it. Use explicit session dates for historical or mock work. The full morning and evening wrappers are retained for the eventual live-capable architecture, but the current project boundary remains research/shadow and the code reports `ROUTER ACTIVE: FALSE` and `NO ORDER WAS SENT`.

## Validation commands

The dependency-free canonical contract check can run before third-party
packages or local market data are restored:

```powershell
python .\tools\validate_canonical_pipeline.py
```

It verifies the stage order, research-only safety flags, centralized ledger
and output boundaries, required entry points, and current project guides.

The project-level validation runner performs compile checks and configuration JSON checks. By default it also runs the full project test suite:

```powershell
.\tools\run_project_validation.ps1
```

Useful narrower forms:

```powershell
# Static checks without importing third-party packages or running tests.
.\tools\run_project_validation.ps1 -StaticOnly

# Compile/config/package checks, but skip pytest.
.\tools\run_project_validation.ps1 -SkipTests

# Explicitly validate the frozen install payload when working on that package.
.\tools\run_project_validation.ps1 -StaticOnly -CheckVerifiedPackage

# Existing focused V2 lifecycle validation.
.\run_step9_morning_v2_validation.ps1

# Fast canonical contract/safety test set.
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider `
    tests/test_step9_morning_v2_install_contract.py `
    tests/test_step9_morning_v2_persistent_worker.py `
    tests/test_step9_morning_v2_support.py `
    tests/test_step9_full_morning_safety_v1.py

# Existing historical validation suite.
.\run_v1_validation_suite.ps1
```

The validation runner is read-only with respect to the real project databases. Full compatibility/preflight scripts may create isolated validation copies and generated reports; they must not be treated as ordinary unit tests.

The frozen Step 9 Morning V2 install payload is historical evidence. Its package check is opt-in because its embedded runtime manifest can legitimately predate the current centralized data paths.

Runtime-manifest hashes normalize text line endings before comparison, so the same audited source remains reproducible across Windows CRLF and repository/CI LF checkouts. SQLite databases, CSV files, and other non-text payloads remain byte-hashed.

## Local data acquisition and restoration

Market databases, ledgers, generated outputs, archives, and proprietary exports are intentionally excluded from Git. A fresh checkout therefore contains the code and contracts but not the local research payload.

### Data categories

- `data/source/market/`: reusable intraday and Nasdaq/Yahoo source databases and raw collector inputs.
- `data/source/reference/`: instrument taxonomy, registries, and reconciliation references.
- `data/ledgers/prospective/`: immutable prospective shadow ledgers.
- `data/ledgers/research/`: research-only databases such as Step 9R candidate-ranking research.
- `data/outputs/`: generated shadow, collector, KPI, Power BI, session, and research outputs.
- `data/archives/`: frozen and historical evidence.

### Restore order on a new machine

1. Clone or open the repository and run `setup_regime_trading.ps1`.
2. Restore the latest trusted `Regime trading` data snapshot or backup into the matching `data/` subdirectories, preserving SQLite sidecars (`.db-wal`, `.db-shm`, and `.db-journal`) with their database.
3. Restore source/reference data before prospective ledgers. Do not merge mock or historical ledgers into prospective ledgers.
4. Restore generated outputs only when their provenance is needed; they can usually be regenerated from source data and configuration.
5. Run `.\tools\run_project_validation.ps1 -SkipTests` and then the relevant focused tests.
6. Confirm that `config\paths.json`, `config\stage_registry.json`, and the runtime manifest point to the restored locations. Do not edit historical hashes merely to make a moved or incomplete dataset pass.

### Acquiring fresh market data

- Step 9H holdout data: `.\collect_step9h_holdout_data.ps1`
- Step 9I V2 shadow data: `.\collect_step9i_v2_shadow_data.ps1`
- Nasdaq forward/post-trade data: `.\run_nasdaq_collection.ps1`

These collectors require network access, provider credentials/configuration where applicable, and a deliberate session/date choice. They write to the configured local data roots and should not be run as part of ordinary validation.

### Provenance rule

Keep the source snapshot, ledger snapshot, generated reports, and manifest/hash files together. If a snapshot is copied from another computer, record its origin and capture date in the relevant migration or restore note before using it for research.
