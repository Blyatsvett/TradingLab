# Secondary Project Audit

Audit date: 2026-08-01

This is a lightweight status audit of the projects secondary to Regime Trading. It records the current operational boundary without changing their scripts, data, or generated outputs.

## Classifications

| Project | Classification | Evidence | Boundary |
|---|---|---|---|
| `Swing/` | Active — research-only | Canonical v1 backtest runner exists; four canonical tests pass; Power BI-ready outputs are generated under `outputs/canonical/`. | No production orders, broker integration, or live-trading claim. Legacy scripts remain for reference and are outside the canonical runner. |
| `Pattern Trading/` | Research-only | Independent Black Friday and Labor Day event-study projects have runners, tests, configs, and local outputs. | No order or execution workflow. `super_bowl/` is retained as paused/legacy research material because it currently has no active implementation. |
| `Intraday/` | Active — research and paper-trading-only | The daily ORB workflow downloads data, scans, updates paper trades, creates paper trades, and produces research/shadow reports. | No broker/live-order path in the canonical workflow. Research universes and shadow strategies are explicitly separate from the production ORB basket. |

## Per-project notes

### Swing

The canonical entry point is `python -m scripts.run_canonical_backtest`, with tests under `tests/`. The project is active because the canonical pipeline and test boundary are maintained, but its use is limited to research/backtesting. The invalid or historical scripts found elsewhere in the folder were not modified or promoted into the canonical path.

### Pattern Trading

Pattern Trading is a collection of event-study research, not one unified trading engine. Black Friday and Labor Day are the active research children. `super_bowl/` is not treated as active until it has an implementation, documented entry point, and validation boundary. Local datasets, databases, and outputs stay outside Git.

### Intraday

The canonical entry point is `run_intraday_workflow.ps1`, which invokes the daily ORB workflow. Its outputs include paper-trading records and research/shadow reports. The existence of paper-trading code does not imply live execution; no broker submission path was identified in this audit.

## Follow-up rule

Do not move, rename, delete, or rewrite secondary-project operational scripts based only on this classification. Revisit a project when its owner, canonical entry point, or execution boundary changes.
