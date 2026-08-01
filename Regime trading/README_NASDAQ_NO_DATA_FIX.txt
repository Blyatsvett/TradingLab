NASDAQ COLLECTOR NO-DATA FIX
============================

Purpose
-------
Nasdaq publishes minute report identifiers during periods where no trade table
may be present (commonly pre-open/no-trade minutes). Collector V1 treated empty
or separator-only files as parser failures, left them in data/nasdaq_raw/incoming,
and retried them on every run.

Changes
-------
- Empty files are classified as NO_DATA, not FAILED.
- Files containing only a quoted or unquoted sep=; declaration are NO_DATA.
- NO_DATA files are archived normally and removed from incoming.
- PROCESSED and NO_DATA report IDs are both terminal and skipped later.
- collection_runs gains a no_data_reports counter through an automatic,
  backward-compatible SQLite migration.
- HTML/error responses remain failures and are not silently accepted.
- No strategy logic or Yahoo/V1 research input is changed.

Installation
------------
Extract this ZIP directly into the existing project root:
C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

Allow replacement of:
RegimeTrading\core\nasdaq_database.py
RegimeTrading\scripts\collect_nasdaq_posttrade.py

Cleanup existing files without downloading again
-------------------------------------------------
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.collect_nasdaq_posttrade --skip-download

Then rebuild comparison exports
-------------------------------
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.compare_nasdaq_yahoo
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.compare_gap_recovery_decisions
.\.venv\Scripts\python.exe -m RegimeTrading.scripts.export_powerbi_workbook

Expected cleanup result
-----------------------
The first --skip-download run should show a large No-data reports count and
zero (or very few genuine) Failed reports. Later runs should not retry those
same empty files.
