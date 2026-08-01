# Regime Trading Data Restore Rehearsal

Date: 2026-08-01  
Status: passed

## Snapshot

- Source: current local `Regime trading` project and data tree
- Snapshot method: `CREATE_FRESH_REGIME_TRADING_SNAPSHOT.ps1`
- Snapshot contents: code, configuration, tests, local data, ledgers, outputs,
  archives, and Power BI files; virtual environment and Git metadata excluded
- Snapshot SHA-256: `747f98cdaa4f522161b0b76864dfb3957a723e6af6a7ad5a3ea6ddf5e0cb7ff4`

## Restore checks

The snapshot was extracted into an isolated temporary project root. The live
project data tree was not modified.

- Static project validation: passed
- Python compilation: passed
- Canonical pipeline contract: passed
- Configuration JSON validation: passed for 15 files
- Restored path resolution: passed with `REGIME_TRADING_DATA_DIR` and
  `REGIME_TRADING_SOURCE_INTRADAY_DB` pointed at the restored tree
- Restored source, reference, ledger, output, and archive directories: present
- Restored intraday source database: present

## Restore procedure for a new machine

1. Extract the trusted snapshot into a new project directory.
2. Create the project environment with `setup_regime_trading.ps1`.
3. Point `REGIME_TRADING_DATA_DIR` and `REGIME_TRADING_SOURCE_INTRADAY_DB` at
   the restored tree when the sibling Intraday project is not available.
4. Run `tools/run_project_validation.ps1 -SkipTests`.
5. Restore or verify SQLite sidecars together with their database before
   running any stage that requires a live local data payload.
6. Run the focused tests for the restored stage before any research workflow.
