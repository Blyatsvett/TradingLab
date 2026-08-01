# TradingLab

TradingLab is a multi-project quantitative trading research workspace for Swedish and US equities.

## Current priorities

1. **Regime Trading** — primary project and current focus.
2. **Swing** — active swing research and backtesting.
3. **Pattern Trading** — event and pattern research.
4. **Intraday** — ORB and intraday research workflows.
5. **Trading Beta** — legacy first project, retained for reference.

The overall system is currently research/backtesting only. Live trading is a future capability, not an assumption of the current code.

## Repository layout

| Folder | Purpose |
|---|---|
| `Regime trading/` | Main active research platform |
| `Swing/` | Swing strategy research |
| `Pattern Trading/` | Pattern and event-study research |
| `Intraday/` | Intraday strategy research and paper workflows |
| `Trading Beta/` | Legacy project and its historical dashboards/data/scripts |
| `Training/` | Shared notes, plans, and visual references |
| `Regime trading backups/` | Historical Regime Trading snapshots |
| `Regime trading mock sessions/` | Simulated or test sessions |

## Working in Codex

Open this `TradingLab` folder as the project in the desktop app. Read `AGENTS.md` before making changes. Start with an inventory and a baseline test run before refactoring project internals.

For the current folder ownership and independent project commands, see [`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md).

## Repository boundary

Source code, configurations, project documentation, and reproducible research definitions belong in Git. Local databases, downloaded/raw data, generated outputs, archives, virtual environments, and proprietary dashboard exports remain local and are excluded by `.gitignore`.

The current checkout is the local repository baseline for the reorganized workspace. GitHub synchronization is a separate, deliberate step after the baseline has been reviewed.
