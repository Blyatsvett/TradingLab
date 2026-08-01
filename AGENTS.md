# TradingLab working agreements

## Project map

- `Regime trading/` is the primary active project and the current priority.
- `Swing/`, `Pattern Trading/`, and `Intraday/` are separate active projects.
- `Trading Beta/` is the legacy first project. Preserve it for reference, but do not treat it as the default source of truth for new work.
- `Training/` contains shared notes, plans, and visual references.
- `Regime trading backups/` and `Regime trading mock sessions/` are historical or simulated material. Do not edit them unless explicitly requested.

## Research stage

The projects are currently in research and backtesting. Live-trading infrastructure may be added later, but no change should imply live execution or real capital access unless explicitly requested.

## Current source of truth

- `Regime trading/` is the canonical active project for current work, with Regime Trading as the main priority.
- Its authoritative project map is maintained in `Regime trading/docs/ACTIVE_SYSTEM_GUIDE.md`.
- Data migration and classification records are maintained in `Regime trading/docs/DATA_MIGRATION_MANIFEST_V1.md`, `Regime trading/docs/DATA_SEPARATION_MAP.md`, and `Regime trading/docs/ROOT_DATA_CLASSIFICATION_V1.md`.
- This root `AGENTS.md` is the single project-wide working-agreement file. Update it when the project structure or operating rules change.
- The concise project ownership and command map is maintained in `docs/PROJECT_MAP.md`.

## Regime Trading data layout

- `Regime trading/data/source/` contains market sources and reusable reference data.
- `Regime trading/data/ledgers/` contains prospective and research databases.
- `Regime trading/data/outputs/` contains generated research, shadow, collector, KPI, and observer outputs.
- `Regime trading/data/archives/` contains frozen, legacy, and historical research material.
- Do not place new project files directly under `Regime trading/data/`; use the appropriate category folder.

## Active priority and execution boundary

- Regime Trading is in research/backtesting. Orders remain disabled and the router remains inactive.
- Keep existing scripts and pipelines runnable, including legacy research scripts, while routing their outputs through configured path helpers.
- Treat databases and SQLite sidecars as one migration unit.
- Preserve frozen manifests, source hashes, and historical provenance strings even when their referenced live files have moved.

## Independent project environments

- Regime Trading: `Regime trading/setup_regime_trading.ps1`, then `Regime trading/tools/run_project_validation.ps1`.
- Swing: `Swing/setup_swing.ps1`, then `Swing/validate_swing.ps1` or `Swing/run_swing_backtest.ps1`.
- Pattern Trading: `Pattern Trading/setup_pattern_trading.ps1`, then `Pattern Trading/validate_pattern_trading.ps1`.
- Intraday: `Intraday/setup_intraday.ps1`, then `Intraday/validate_intraday.ps1` or `Intraday/run_intraday_workflow.ps1`.

Run each command from its owning project folder. Do not use the root workspace environment as a substitute for a project environment.

## Safety and reproducibility

- Keep raw data, generated outputs, credentials, and local environments out of source control.
- Prefer additive changes and preserve historical experiments unless the user explicitly asks for cleanup or deletion.
- Before changing a strategy, identify its data source, date range, execution assumptions, transaction costs, and look-ahead protections.
- Run the narrowest relevant tests after code changes and report what was run.
- Do not silently overwrite research results or change canonical configurations.

## Organization

- New reusable Python code belongs in the relevant project package, not in an ad-hoc root script.
- New experiments should be clearly named and kept separate from canonical pipelines.
- Document major research decisions and assumptions in Markdown near the project that owns them.
