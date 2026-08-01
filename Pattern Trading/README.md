# Pattern Trading

Pattern Trading contains independent event-study research projects. It is research-only and does not place orders.

Black Friday and Labor Day are the active research children. `super_bowl/` is paused/legacy pending a documented implementation and validation boundary.

## Setup

From this folder in PowerShell:

```powershell
.\setup_pattern_trading.ps1
```

## Validation

```powershell
.\validate_pattern_trading.ps1
```

## Child projects

- `black_friday_event_study/`: run `.\run_black_friday_pipeline.ps1` after setup.
- `labor_day_event_study/`: run `.\run_labor_day_tests.ps1` or the ingestion tools from that project root.
- `super_bowl/`: retained research material; inspect its local README or scripts before running.

Downloaded data, databases, and generated outputs remain local and are excluded from Git.
