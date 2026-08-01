# Contributing to TradingLab

TradingLab is a multi-project quantitative research workspace. The current default is research/backtesting; live trading is not assumed.

## Before opening a change

1. Read the root `AGENTS.md` and the relevant project README.
2. Keep the change inside the owning project folder unless it is genuinely repository-wide.
3. Do not commit local databases, downloaded market data, generated outputs, credentials, or virtual environments.
4. Identify the canonical entry point before changing a script. A script's presence does not make it part of the active workflow.

## Validation

Run the narrowest relevant project validation locally. The pull-request checks run the same code-only boundaries through `.github/workflows/ci.yml`.

- Regime Trading: `tools/run_project_validation.ps1 -SkipTests`, then the focused safety tests when code changes require them.
- Swing: `validate_swing.ps1`.
- Pattern Trading: `validate_pattern_trading.ps1`.
- Intraday: `validate_intraday.ps1`.

Do not run market-data acquisition or daily paper-trading workflows as a substitute for tests.

## Pull requests

Use the pull-request template. Keep one logical change per pull request, describe the affected project, and report the exact validation performed. Reviewers should confirm that no live-order boundary, data provenance rule, or canonical output path changed unintentionally.
