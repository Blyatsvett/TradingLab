NASDAQ NORDIC FREE-DATA PHASE 1A
================================

This patch adds a read-only provider probe. It downloads the newest available
Nasdaq Nordic equity post-trade CSV into:

  data\nasdaq_raw\probe

It prints the exact column names, delimiter, encoding and three sample rows.
It does not modify intraday_prices.db, research CSV files or Power BI exports.

INSTALL
-------
Extract this patch over:

  C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

Then install the added Selenium dependency:

  cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt

RUN
---
  .\probe_nasdaq_data.ps1

Chrome must be installed. Selenium Manager normally resolves a compatible
ChromeDriver automatically.

NEXT STAGE
----------
Use the printed schema to build the persistent collector safely:

  data\nasdaq_forward_data.db
    - downloaded_files
    - nasdaq_trades
    - nasdaq_5m_bars

The existing Yahoo snapshot remains in data\intraday_prices.db and is not
changed. The two sources will first be compared during overlapping dates.
Only after quality checks pass should a combined research input be considered.
