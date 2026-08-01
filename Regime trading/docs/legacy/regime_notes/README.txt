REGIME TRADING - STANDALONE RESEARCH PROJECT
============================================

CURRENT SYSTEM NOTICE
---------------------
This file documents the original standalone gap-recovery workflow. The current
Regime Trading system is the Step 9 research/shadow pipeline. Start with:

docs\ACTIVE_SYSTEM_GUIDE.md

Do not use the commands below as the default daily pipeline without confirming
that the task belongs to the legacy gap-recovery workflow.

Target installation path
------------------------
C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

Isolation design
----------------
- This is a separate Python package named RegimeTrading.
- It does not import or execute production ORB scripts.
- It does not modify the original Intraday project.
- It has its own local data directory, logs, Power BI workbook, virtual
  environment, workflow, execution helper, and research configuration snapshot.
- The original intraday_prices.db is opened read-only and copied into this
  project's local data directory through SQLite's backup API.
- All research then runs against the local database copy.

Project structure
-----------------
Regime trading\
  RegimeTrading\
    core\
    scripts\
  data\
  logs\
  requirements.txt
  setup_regime_trading.ps1
  run_regime_research.ps1
  run_research_only.ps1

First-time setup
----------------
Open PowerShell:

cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
Set-ExecutionPolicy -Scope Process Bypass
.\setup_regime_trading.ps1

Run the complete isolated workflow
----------------------------------
.\run_regime_research.ps1

The workflow performs only these research actions:
1. Copy the original intraday database into the isolated data folder.
2. Run REGIME_AWARE_GAP_RECOVERY_V1.
3. Export the isolated Power BI workbook.
4. Validate the generated files and schemas.

Manual Python commands
----------------------
cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"

.\.venv\Scripts\python.exe -m RegimeTrading.scripts.sync_intraday_database
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.research_regime_aware_gap_recovery
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.export_powerbi_workbook
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.validate_outputs

Local database
--------------
Source, read-only:
C:\Users\User\Desktop\Kaizen\TradingLab\Intraday\data\intraday_prices.db

Local research copy:
C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\data\intraday_prices.db

To change the source temporarily:
$env:REGIME_TRADING_SOURCE_DB = "D:\another\intraday_prices.db"
.\run_regime_research.ps1

Power BI source
---------------
C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading\data\powerbi_exports.xlsx

The workbook contains only Regime Gap Recovery research tables. It does not
contain production ORB or paper-trading tables.

Generated research files
------------------------
regime_gap_recovery_summary.csv
regime_gap_recovery_trades.csv
regime_gap_recovery_daily.csv
regime_gap_recovery_latest.csv
regime_gap_recovery_candidates.csv
regime_gap_recovery_forward_summary.csv
regime_gap_recovery_forward_trades.csv
regime_gap_recovery_forward_daily.csv
regime_gap_recovery_forward_candidates.csv

Production protection
---------------------
The production package remains at:
C:\Users\User\Desktop\Kaizen\TradingLab\Intraday

The standalone workflow never calls:
- Intraday.scripts.orb_daily_scanner
- Intraday.scripts.update_paper_trades
- Intraday.scripts.auto_create_triggered_paper_trades
- Any production execution or paper-trading module

The frozen ticker/capital/cost values are copied into a clearly labeled
research-only snapshot at RegimeTrading\core\research_config.py. Editing that
snapshot cannot change production behavior.
