# Root Data Classification V1

Status: classification completed. Source/reference data, Nasdaq collector assets, the Step 9M/N/O legacy families, and the Step 9T reconciliation input are now centralized. Remaining root-level items are limited to intentional placeholders or files awaiting a final documentation pass.

## Active source data and registries

These files are inputs, registries, or collector state and should not be archived as generated output:

- `data/intraday_prices.db` — original intraday source used through the shared source configuration.
- `data/step9h_holdout_intraday_prices.db` — holdout market-data source.
- `data/instrument_static_taxonomy.csv`
- `data/instrument_characteristic_definitions.csv`
- `data/instrument_point_in_time_characteristics.csv`
- `data/instrument_group_daily_state.csv`
- `data/instrument_relationship_constraints.csv`
- `data/regime_holdout_universe_registry.csv` — runtime holdout registry and manifest-fingerprinted input.
- `data/nasdaq_forward_data.db` with its `-wal`/`-shm` sidecars — active collector database; these must move as one unit when references are centralized.
- `data/nasdaq_raw/` — raw collector area.

## Active shadow outputs and ledgers

The ledgers are centralized under `data/ledgers/prospective/`; the CSV outputs are centralized under versioned shadow-output folders:

- `data/outputs/shadow/step9i_v2/`
- `data/outputs/shadow/step9l_v3/`
- `data/ledgers/prospective/step9r_prospective_selector_shadow_v1.db`
- `data/ledgers/research/step9r_candidate_ranking_research_v1.db`

The Step 9R databases are now centralized; their active consumers and validation references resolve through the stage registry.

The Step 9S/9T/9U historical research outputs and Step 9V observer outputs are now centralized under:

- `data/outputs/research/step9s_historical_contingency_replay_v1/`
- `data/outputs/research/step9t_regime_transition_archetype_research_v1/`
- `data/outputs/research/step9u_historical_contingency_selector_v1/`
- `data/outputs/observer/step9v_intraday_regime_transition_observer_v1/`

The configured Step 9S/9T/9U/9V ledger paths now point under `data/ledgers/prospective/`; no corresponding physical database files were present in this workspace to migrate.

The remaining source and collector layout is:

- `data/source/market/intraday_prices.db`
- `data/source/market/step9h_holdout_intraday_prices.db`
- `data/source/market/nasdaq_forward_data.db` with its sidecars
- `data/source/market/nasdaq_raw/`
- `data/source/reference/` for instrument taxonomy and holdout registry files
- `data/source/reference/reconciliation/july28_ticker_market_performance.csv`
- `data/outputs/collector/nasdaq/` for current collector snapshots and comparisons

Step 9M/N/O outputs are archived under `data/archives/research/step9m/`, `step9n/`, and `step9o/`.

## Active collector snapshots

The following are current/latest collector status or comparison products and should remain paired with the collector path until that path is centralized:

- `data/nasdaq_5m_bars_latest.csv`
- `data/nasdaq_collection_status.csv`
- `data/nasdaq_instrument_coverage.csv`
- `data/nasdaq_yahoo_bar_comparison.csv`
- `data/nasdaq_yahoo_opening_range_comparison.csv`
- `data/nasdaq_yahoo_strategy_decision_comparison.csv`
- `data/nasdaq_yahoo_strategy_decision_summary.csv`

## Legacy research outputs requiring a dedicated producer audit

These are generated historical research families, but their scripts are still runnable and write directly to the root. They are therefore classified as legacy-generated, not yet migrated:

- `data/step9m_*.csv`
- `data/step9n_*.csv`
- `data/step9o_*.csv`

Before moving them, their producers and the Step 9N/9O dependency chain must resolve through the family path helper.

## Historical research input

- `data/july28_ticker_market_performance.csv` — historical reconciliation input consumed by the Step 9T verifier. It requires a path update and replay check before relocation.

## Completed in this pass

- `data/powerbi_exports.xlsx` → `data/outputs/kpi/powerbi_exports.xlsx`

The root source/legacy classification is also recorded in `config/data_migration_manifest_v1.json`.
