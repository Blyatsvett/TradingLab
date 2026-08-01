REGIME-ADAPTIVE SYSTEM — STEP 9E
INSTRUMENT, SECTOR AND TICKER-CHARACTERISTIC TAXONOMY

Purpose
-------
Build a frozen descriptive foundation for structured sector/ticker experiments.
Step 9E does not change Step 9D trades, rank challengers, promote a strategy, or
activate any router rule.

Version
-------
Taxonomy: INSTRUMENT_SECTOR_TICKER_TAXONOMY_V1
Status  : SIMULATION_ONLY_FOUNDATION_NOT_ROUTER_ACTIVE
Decision time: 09:45
Latest same-day bar label: 09:40

What is added
-------------
1. Versioned stable metadata for all 11 research ticker symbols.
2. Ten independent company identities; Atlas Copco A/B are one company.
3. Broad sector, industry, macro-sensitivity cluster and peer-group labels.
4. Company-observation weights so multiple share classes do not double-count.
5. Prior-only 20-session volatility, beta, correlation, range, gap, momentum,
   early-move followthrough and early-move reversal characteristics.
6. Same-day 09:40 gap, range, market-relative, sector-relative and cluster-relative state.
7. Company-weighted daily state for sectors, clusters and peer groups.
8. Explicit safeguards for share classes, pairs, single-company groups and liquidity assumptions.
9. Point-in-time and completeness audits.

Interpretation safeguards
-------------------------
- Formal business sectors and research economic clusters are separate concepts.
- A group with fewer than two independent companies is labelled SINGLE_COMPANY_PROXY.
- Static liquidity labels are assumptions, not measured historical liquidity.
- Beta uses the company-weighted internal research universe, not an external market index.
- Followthrough/reversal rates are descriptive historical tendencies, not strategies.
- No Step 9E output is router-active.

Files created
-------------
data\instrument_taxonomy_summary.csv
data\instrument_static_taxonomy.csv
data\instrument_characteristic_definitions.csv
data\instrument_point_in_time_characteristics.csv
data\instrument_group_daily_state.csv
data\instrument_taxonomy_completeness.csv
data\instrument_relationship_constraints.csv
data\instrument_taxonomy_audit.csv

Run
---
cd "C:\Users\User\Desktop\Kaizen\TradingLab\Regime trading"
.\run_step9e_instrument_sector_taxonomy.ps1

Full workflow
-------------
.\run_regime_research.ps1

Tests
-----
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

Expected test count after this patch: 86

Mechanical pass classification
------------------------------
INSTRUMENT_TAXONOMY_READY_FOR_SECTOR_STRATEGY_EXPERIMENTS

Next step
---------
Step 9F will consume this frozen taxonomy to run structured market-regime ×
strategy × sector/cluster/ticker experiments with company and sample-size safeguards.
