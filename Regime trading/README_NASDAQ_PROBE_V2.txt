NASDAQ PHASE 1 PROBE V2
=======================

Replace these files relative to your existing project root:

RegimeTrading\scripts\probe_nasdaq_posttrade.py
probe_nasdaq_data.ps1

Then run from:
C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading

.\probe_nasdaq_data.ps1

V2 first tries direct HTTP discovery. If the report links are rendered only in the
browser, it opens a visible Chrome window. This avoids the headless timeout seen
in V1 and prints useful diagnostics if Nasdaq serves an interstitial or error page.

No SQLite database or strategy output is changed.
