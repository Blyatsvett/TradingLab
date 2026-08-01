# Labor Day Event Study — Price Data Contract

**Phase:** 1A  
**Status:** Frozen design contract  
**Universe file:** `config/labor_day_universe.csv`  
**Eligibility panel:** `data/processed/labor_day_universe_by_year.csv`

## 1. Purpose

Phase 1 converts the completed event and macro infrastructure into a
reproducible market-price dataset. This contract defines which instruments
may enter each Labor Day event year, how benchmarks are resolved, which raw
fields must be retained, and which quality checks must pass before returns
are calculated.

The contract intentionally separates four questions:

1. Is an instrument part of the economic hypothesis?
2. Did that instrument have usable public price history in that event year?
3. Which benchmark was actually available in that year?
4. Is the provider history continuous through corporate actions and ticker
   changes?

A current ticker is never assumed to have existed throughout 1998–2026.

## 2. Frozen hypotheses

| Hypothesis | Economic channel | Primary benchmark |
|---|---|---|
| `refining_gasoline` | End-of-summer driving, gasoline demand, refining margins | `XLE` |
| `auto_dealers` | Model-year clearance and Labor Day vehicle promotions | `XLY` |
| `domestic_leisure_travel` | Holiday travel demand across lodging, cruise, airlines, and online travel | `XLY` |
| `generic_control` | Broad-market, sector, size, and unrelated-sector controls | `SPY` or none |

`SPY` is the market benchmark and the fallback benchmark when a sector ETF
did not yet exist. `XLU` is an unrelated-sector negative control. `IWM` is a
size control.

## 3. Dynamic eligibility

Eligibility is evaluated for each `event_year × ticker`.

An instrument is eligible only when all of the following hold:

- `analysis_start_year <= event_year`;
- `analysis_end_year` is blank or `event_year <= analysis_end_year`;
- the relevant sample flag is true;
- the raw price-quality audit confirms sufficient history around the event;
- any required symbol-continuity review has passed.

Sample boundaries are frozen:

- discovery: 1998–2014;
- validation: 2015–2025;
- forward: 2026.

The CSV flags describe whether an instrument can participate in a sample at
all. They do not force inclusion in years before its analysis start.

## 4. Benchmark resolution

Benchmark resolution is deterministic:

1. Use `primary_benchmark` when it is eligible in the event year.
2. Otherwise use `fallback_benchmark`.
3. `SPY`, the market benchmark, resolves to no benchmark.

Examples:

- `VLO` in 1998 uses `SPY`.
- `VLO` from 1999 onward uses `XLE`.
- Auto-dealer and travel stocks in 1998 use `SPY`.
- Auto-dealer and travel stocks from 1999 onward use `XLY`.

No benchmark series may be synthetically backfilled before its own eligible
start year.

## 5. Analysis tiers

`core` instruments provide the longest or most direct exposure and form the
principal basket where available.

`extension` instruments improve later-period breadth but have shorter public
histories or entity-continuity limitations. They must be reported
separately in robustness tables before being blended with the core basket.

Equal weights are recalculated separately for each hypothesis and event
year. Missing later entrants therefore do not dilute early baskets.

## 6. Continuity policy

### `continuous`

The same canonical series is expected through the eligible period. The
price audit must still test splits, missing sessions, and extreme jumps.

### `predecessor_continuity`

The provider may expose earlier observations under a current ticker even
though the historical symbol differed. These rows require explicit review.

Frozen predecessor cases:

- `DINO` ← `HFC`;
- `PAG` ← `UAG`;
- `BKNG` ← `PCLN`.

The pipeline must not concatenate two symbol files merely because the dates
do not overlap. It must verify that they represent the same economic equity
claim and that adjustment factors are continuous.

### `current_public_era`

Only the current public-company era is admissible. Earlier predecessor,
pre-bankruptcy, pre-merger, or pre-private-equity histories are not stitched
into the core series.

Frozen current-era cases:

- `MPC`;
- `PSX`;
- `PBF`;
- `HLT`;
- `DAL`;
- `UAL`.

## 7. Primary price source

Phase 1B will use Yahoo Finance through a pinned `yfinance` dependency as the
primary retrieval layer.

Required retrieval settings:

- `auto_adjust=False`;
- corporate actions requested;
- one ticker per cached raw response;
- deterministic date range;
- threading disabled for reproducible logs;
- no silent repair or forward filling.

This is a convenience source, not an official exchange record. Raw responses
and provider metadata must therefore be retained, hashed, and subjected to
the Phase 1C quality audit.

A second source may be used for targeted verification of flagged rows, but
it must not silently overwrite the primary raw history.

## 8. Required raw fields

The normalized daily dataset must contain:

| Column | Meaning |
|---|---|
| `ticker` | Canonical project ticker |
| `provider_symbol` | Symbol sent to the data provider |
| `session_date` | Exchange trading date |
| `open` | Unadjusted open |
| `high` | Unadjusted high |
| `low` | Unadjusted low |
| `close` | Unadjusted close |
| `adjusted_close` | Provider total-return adjusted close |
| `volume` | Reported share volume |
| `dividend` | Cash dividend on the session |
| `split` | Split ratio/action value |
| `retrieved_utc` | Retrieval timestamp |
| `source` | Provider identifier |
| `source_file` | Cached raw-file reference |

Numeric blanks remain missing. They are never converted to zero except when
the provider explicitly reports zero dividend or zero split action.

## 9. Adjustment policy

Both raw and adjusted prices are retained.

- Total-return and abnormal-return calculations use `adjusted_close`.
- Execution-oriented analyses retain raw open and close values.
- An adjustment factor is calculated as
  `adjusted_close / close`.
- Adjusted OHLC values may be derived by multiplying raw OHLC by the
  adjustment factor.
- A zero, negative, or non-finite adjustment factor is a critical error.

Provider-adjusted data is not accepted merely because it downloads
successfully. Phase 1C must identify unexplained discontinuities around
splits, dividends, mergers, and ticker changes.

## 10. Date range and sessions

The requested history begins no later than `1997-01-01`. This provides
pre-event observations for the first 1998 Labor Day event.

The end date is the latest available completed U.S. market session at
retrieval time. The 2026 forward event remains incomplete until post-Labor
Day sessions exist; it must be labeled forward/incomplete rather than
silently dropped or treated as a failed download.

`session_date` is the U.S. exchange date. Datetime conversion must not shift
a session into the previous or next date through UTC normalization.

Expected sessions come from the project’s frozen NYSE calendar. Price
providers may omit a session only when the instrument was not yet eligible,
was halted, or has a documented instrument-specific exception.

## 11. Raw cache contract

Phase 1B writes immutable raw files under:

```text
data/raw/prices/yahoo/
```

A cache filename must include at least:

- canonical ticker;
- provider symbol;
- requested start date;
- requested end date;
- a deterministic request hash.

A cached file is never edited in place. A changed request creates a new
cache artifact. The normalized output is rebuilt from cached raw files.

## 12. Normalized output

Phase 1B will create:

```text
data/processed/daily_prices.csv
manifests/daily_prices_manifest.json
```

The manifest must record:

- universe hash;
- provider and library version;
- request parameters;
- retrieval timestamp;
- raw file hashes;
- normalized output hash;
- row counts by ticker;
- first and last session by ticker;
- failures and retries.

Re-running with the same universe, date range, provider version, and cached
inputs must produce the same normalized output hash.

## 13. Phase 1C quality checks

The price-quality audit must detect:

### Structural failures

- duplicate `ticker × session_date`;
- unsorted or unparsable dates;
- missing required columns;
- non-numeric OHLC or adjustment fields;
- zero or negative prices;
- negative volume;
- impossible OHLC relationships;
- duplicate raw cache identities.

### Coverage failures

- first usable session after the policy start;
- insufficient pre-event estimation history;
- missing event-window sessions;
- missing benchmark overlap;
- unexplained long gaps;
- 2026 forward incompleteness incorrectly classified as historical failure.

### Corporate-action warnings

- extreme unadjusted jumps without split records;
- adjusted-price discontinuities around ticker changes;
- predecessor histories beginning earlier than policy allows;
- current-public-era histories containing inadmissible predecessor data.

Outputs:

```text
data/processed/price_coverage_by_ticker.csv
data/processed/price_quality_issues.csv
manifests/price_quality_audit.json
```

## 14. Survivorship-bias limitation

The frozen Phase 1A stock universe consists primarily of companies that
remain publicly identifiable today. It is not a complete historical
constituent set for each industry.

Therefore:

- ETF and long-history anchor results are primary;
- current-survivor stock baskets are labeled as such;
- extension-stock results are robustness evidence;
- no claim may be made that the basket represents all companies that were
  investable in each historical year;
- a later delisted-security extension may be added as a separate,
  versioned universe rather than changing this frozen universe silently.

## 15. Phase 1 exit criteria

Phase 1 is complete only when:

1. the universe validates;
2. the year panel is reproducible;
3. all raw price files are cached and hashed;
4. historical benchmark overlap is resolved;
5. all critical price-quality issues are zero;
6. continuity warnings are either resolved or explicitly excluded;
7. the Labor Day market panel can be built without silent imputation;
8. the full project test suite passes.

Any change to an instrument, start year, continuity policy, or benchmark
requires a new universe version and a new manifest hash.
