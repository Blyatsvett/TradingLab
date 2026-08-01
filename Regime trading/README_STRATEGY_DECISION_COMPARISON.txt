NASDAQ/YAHOO GAP RECOVERY STRATEGY-DECISION COMPARISON
=====================================================

Purpose
-------
This is a shadow data-quality comparison for REGIME_AWARE_GAP_RECOVERY_V1.
It does not change the V1 research input, production ORB, or paper trading.

Method
------
Both Yahoo and Nasdaq candidate engines use:
- the same Yahoo-derived previous close anchor;
- the same current V1 Yahoo early-market regime label;
- the exact current V1 gap, opening-range, entry, stop, target, timing,
  same-bar STOP priority, cost, and EOD rules.

Only the intraday OHLC bars differ. This isolates whether the provider changes
strategy decisions rather than mixing provider differences with a different
market-regime universe.

The providers are trimmed to the same latest timestamp for each date so one
source cannot appear to trigger simply because it is more up to date.

Files
-----
data/nasdaq_yahoo_strategy_decision_comparison.csv
    One row per overlapping ticker/date with detailed Yahoo and Nasdaq fields,
    price differences, readiness flags, trigger decisions, and outcomes.

data/nasdaq_yahoo_strategy_decision_summary.csv
    Overall and per-ticker match rates.

Run
---
The normal collector now runs this automatically:

    .\run_nasdaq_collection.ps1 -MaxFiles 2000 -LookbackHours 48

Run only the decision comparison:

    .\run_strategy_decision_comparison.ps1

Power BI
--------
The isolated Power BI exporter now includes the two new CSV files. Run:

    .\.venv\Scripts\python.exe -m RegimeTrading.scripts.export_powerbi_workbook

Important interpretation
------------------------
Build and collect now. Do not draw statistical conclusions from only one or two
sessions. The first useful review point is approximately 10 complete sessions;
stronger evidence requires materially more days and actual triggered trades.

Opening-range alignment fix
---------------------------
The existing Nasdaq/Yahoo opening-range diagnostic is aligned with V1:
09:30 <= bar timestamp < 09:35. For five-minute start-labelled bars, this is the
single 09:30 bar. The old diagnostic included the 09:35 bar even though V1 did
not; this patch corrects the diagnostic only and does not change V1.
