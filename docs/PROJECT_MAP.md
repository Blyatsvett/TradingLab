# TradingLab Project Map

TradingLab is a multi-project research workspace. Each project owns its setup, dependencies, entry points, tests, and local data boundary.

| Project | Priority/status | Start/setup | Validation | Main boundary |
|---|---|---|---|---|
| `Regime trading/` | Primary; research/backtesting and prospective shadow | `setup_regime_trading.ps1`; `docs/REPRODUCIBILITY.md` | `tools/run_project_validation.ps1` | Orders disabled; local source data, ledgers, outputs, and archives excluded from Git |
| `Swing/` | Active research/backtesting | `setup_swing.ps1`; `run_swing_backtest.ps1` | `validate_swing.ps1` | Canonical v1 backtest; no production orders |
| `Pattern Trading/` | Independent event-study research | `setup_pattern_trading.ps1` | `validate_pattern_trading.ps1` | Child projects retain separate research datasets and outputs |
| `Intraday/` | ORB, paper trading, and Strategy Lab research | `setup_intraday.ps1`; `run_intraday_workflow.ps1` | `validate_intraday.ps1` | Workflow writes local market data and paper/research outputs; no broker execution |
| `Trading Beta/` | Legacy first project; reference only | No new active setup | Not part of the active baseline | Historical scripts and local payloads retained for reference |
| `Training/` | Notes, visual references, and planning material | N/A | N/A | Documentation/support material, not an executable project |

## Repository-wide rules

- Root `AGENTS.md` is the single project-wide source of truth for working agreements and structure.
- Regime Trading’s canonical system guide and reproducibility runbook are authoritative for that project.
- Keep local databases, downloaded data, generated outputs, archives, virtual environments, and proprietary exports out of Git.
- Run validation from the project folder that owns the code and environment.
- Do not interpret a script’s presence as proof that it is part of the canonical daily chain.

## Where to start

Start with `Regime trading/` for current development. Use `docs/PROJECT_MAP.md` to identify the correct project boundary before changing code or data.
