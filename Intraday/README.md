# Intraday

Intraday contains the ORB, paper-trading, and Strategy Lab workflows. It is separate from Regime Trading and currently supports research and paper workflows only.

Status: active, research and paper-trading-only. The canonical daily workflow does not submit broker or live orders.

## Setup

From this folder in PowerShell:

```powershell
.\setup_intraday.ps1
```

## Commands

```powershell
.\validate_intraday.ps1
.\run_intraday_workflow.ps1
```

The daily workflow downloads/updates local market data and generates paper-trading and research outputs. Do not run it as part of a read-only validation check.
