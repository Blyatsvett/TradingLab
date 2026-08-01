STEP 9H - LOCKED CROSS-SECTIONAL HOLDOUT TRANSPORT
==================================================

Purpose
-------
Test whether three Step 9G discoveries transport to companies that did not participate in discovery.
This is not a new pattern-mining step and cannot activate the router.

Frozen design
-------------
- 18 new Nasdaq Stockholm symbols / 18 independent companies / 9 broad sectors.
- Original ten discovery companies are excluded.
- Original Step 8 market regime taxonomy remains frozen and is not recalculated from holdout outcomes.
- Three primary contracts:
  1) TREND_UP -> range rejection
  2) VOLATILITY_EXPANSION + group alignment -> early continuation
  3) RANGE_LOW_VOL + early laggard + high relative volatility -> delayed reversal
- Complement controls, one same-cohort ORB comparator, and two negative guardrails are fixed.
- Minimum confirmatory sample per contract: 20 trades, 10 sessions, 8 companies, 3 sectors.
- No automatic promotion.

Data isolation
--------------
Holdout data is stored only in:
  data\step9h_holdout_intraday_prices.db

The collector never writes to production or data\intraday_prices.db.

Commands
--------
First update dependencies after applying the patch:
  .\setup_regime_trading.ps1

Collect the currently available 5-minute window:
  .\collect_step9h_holdout_data.ps1

Run the locked transport experiment:
  .\run_step9h_cross_sectional_holdout_transport.ps1

The full workflow also runs Step 9H, but it does not automatically call the network collector.
When data is missing it exports HOLDOUT_DATA_COLLECTION_REQUIRED rather than failing.

Important data limitation
-------------------------
Yahoo/yfinance intraday history is limited to the most recent 60 calendar days. The local database uses
upserts, so rerunning the collector preserves prior rows and lets the locked holdout sample accumulate.
Do not replace the holdout universe or change thresholds because an early sample is weak.
