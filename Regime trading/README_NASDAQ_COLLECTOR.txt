NASDAQ PHASE 1 - PERMANENT FORWARD COLLECTOR
============================================

PURPOSE
-------
This patch adds a persistent Nasdaq Nordic delayed post-trade collector to the
isolated Regime Trading project.

It does NOT alter:
- data/intraday_prices.db
- REGIME_AWARE_GAP_RECOVERY_V1
- the frozen ORB project
- paper trading
- existing Power BI research outputs

Nasdaq data remains diagnostic/shadow-only.

NEW DATABASE
------------
data/nasdaq_forward_data.db

Main tables:
- instrument_map
- collection_runs
- downloaded_reports
- nasdaq_trades
- nasdaq_5m_bars

RAW FILE HANDLING
-----------------
Downloaded minute reports are parsed, filtered to the 11 research instruments,
and compressed into:

data/archives/raw/nasdaq_raw_archive/YYYY-MM-DD/*.csv.gz

The existing probe CSV is imported on the first run but is not deleted.

PRIMARY FIVE-MINUTE BAR FILTER
------------------------------
The comparison bars use only records matching:
- Price currency = SEK
- Price notation = MONE
- Venue of execution = XSTO
- Trading system = CLOB

All selected-instrument records are retained in nasdaq_trades with an
is_primary_lit flag, so alternative venue filters can be researched later.

INSTALLATION
------------
Extract this patch directly into the existing project root:

C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

Do not create another Regime trading folder.

FIRST TEST
----------
Run a limited collection first:

cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
.\run_nasdaq_collection.ps1 -MaxFiles 30

Visible Chrome is the default because headless mode previously failed on the
Nasdaq page. Do not close the Chrome window while report discovery runs.

FULL AVAILABLE BACKFILL
-----------------------
After the limited test succeeds:

.\run_nasdaq_collection.ps1 -MaxFiles 2000 -LookbackHours 48

Already processed report IDs are skipped, so rerunning is safe.

IMPORT/REBUILD WITHOUT BROWSER
------------------------------
To import existing probe/incoming files, rebuild bars, and refresh comparison
exports without opening Chrome:

.\run_nasdaq_collection.ps1 -SkipDownload

OUTPUT CSV FILES
----------------
data/nasdaq_collection_status.csv
data/nasdaq_instrument_coverage.csv
data/nasdaq_5m_bars_latest.csv
data/nasdaq_yahoo_bar_comparison.csv
data/nasdaq_yahoo_opening_range_comparison.csv

DAILY USE
---------
Run the collector separately from run_regime_research.ps1. A suitable initial
routine is once after the Stockholm market closes and once the following
morning if a collection was missed.

The collector only downloads reports that are still available from Nasdaq, so
regular execution is important.

RESEARCH INTEGRATION RULE
-------------------------
REGIME_AWARE_GAP_RECOVERY_V1 continues to read data/intraday_prices.db.
Do not switch it to Nasdaq bars until enough overlapping days have been
collected and the comparison outputs show acceptable opening-range agreement.
