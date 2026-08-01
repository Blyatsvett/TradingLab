STEP 9F - REGIME x STRATEGY x SECTOR/TICKER EXPERIMENTS
========================================================

Purpose
-------
Step 9F keeps all Step 9D trades frozen and enriches them with the Step 9E
instrument taxonomy. It measures strategy outcomes hierarchically by sector,
peer group, company, ticker, and point-in-time instrument state.

This is discovery research only. It does not activate router rules, select a
production strategy, or optimize strategy parameters.

Important interpretation rules
------------------------------
1. A sector or peer result is group evidence only when at least two independent
   companies are represented. Single-company sectors remain ticker/company
   proxies.
2. Atlas Copco A and B remain one independent company. Same-company pair trades
   are invalid and cause the mechanical gate to fail.
3. Economic cluster is audited for redundancy. In the current 11-ticker
   universe it has the same company partition as broad sector, so it is retained
   descriptively but not counted as independent screening evidence.
4. Historical tendency and other state labels are audited for discrimination.
   A dominant category above 80% is flagged for definition review before router
   use.
5. Leave-one-company-out and leave-one-sector-out rows exclude the entire trade
   whenever any leg contains the excluded entity.
6. All rankings are discovery evidence. Strategies promoted remains hard-coded
   to zero.

Run
---
From the project root:

    .\run_step9f_sector_ticker_strategy_experiments.ps1

Or run the complete workflow:

    .\run_regime_research.ps1

Outputs
-------
- data\regime_sector_strategy_summary.csv
- data\regime_sector_strategy_trade_context.csv
- data\regime_sector_strategy_leg_context.csv
- data\regime_sector_strategy_segment_performance.csv
- data\regime_sector_strategy_pair_performance.csv
- data\regime_sector_strategy_exclusion_robustness.csv
- data\regime_sector_strategy_dimension_audit.csv
- data\regime_sector_strategy_state_audit.csv
- data\regime_sector_strategy_rankings.csv

Expected mechanical classification
----------------------------------
SECTOR_TICKER_EXPERIMENT_FOUNDATION_READY_FOR_HIERARCHICAL_REVIEW
