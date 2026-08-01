# Phase 1C — Price Quality and Historical Coverage Audit

## Purpose

Phase 1C determines whether the normalized daily-price dataset is safe to use
for the Labor Day event study. A successful download is not sufficient. Every
ticker must have structurally valid prices, recognized XNYS sessions, complete
historical event windows, usable benchmark overlap, and an explicit continuity
classification.

## Inputs

```text
config/labor_day_universe.csv
data/processed/labor_day_universe_by_year.csv
data/processed/daily_prices.csv
manifests/daily_prices_manifest.json
```

## Outputs

```text
data/processed/price_coverage_by_ticker.csv
data/processed/price_coverage_by_event_year.csv
data/processed/price_quality_issues.csv
manifests/price_quality_audit.json
```

## Frozen event-coverage policy

For every eligible `event_year × ticker` row:

- Labor Day is the first Monday in September.
- The event grid contains 20 XNYS sessions before and 20 after the holiday.
- There is no event-time zero because Labor Day is not an XNYS session.
- Historical years are 1998–2025.
- The 2026 row is `forward_pending` until the post-event sessions exist.
- The estimation window contains the 126 XNYS sessions immediately preceding
  event time -20.
- Benchmark overlap uses the year-specific `resolved_benchmark` produced in
  Phase 1A.
- SPY, as the market benchmark, requires no further benchmark.

The audit uses the official `XNYS` calendar from `exchange_calendars`; it does
not infer future event sessions from the latest Yahoo observation.

## Critical issues

Critical issues make the audit status `FAIL`:

- upstream daily-price manifest is not `PASS`;
- current price, universe, or row count does not reconcile with the upstream
  manifest;
- ticker missing from prices or unknown ticker present;
- duplicate `ticker × session_date`;
- invalid trading date;
- nonnumeric required field;
- zero or negative OHLC/adjusted-close value;
- negative volume;
- impossible OHLC relationship;
- nonpositive or non-finite adjustment factor;
- price row on a non-XNYS date;
- missing historical event-window sessions;
- missing historical benchmark sessions;
- universe start year precedes the first complete historical event year.

The audit always writes its CSVs and manifest before raising, so failed evidence
remains inspectable.

## Warnings

Warnings produce `PASS_WITH_WARNINGS` when no critical issues remain:

- missing XNYS sessions inside a ticker's observed first/last span;
- fewer than 126 common estimation sessions;
- absolute adjusted return above 50%;
- absolute unadjusted return above 50% without a split record;
- adjustment-factor change above 20% without a dividend or split;
- predecessor continuity requiring manual verification.

Warnings do not automatically remove a ticker. They identify observations that
must be examined before the event-study panel is frozen.

## Informational findings

Current-public-era tickers may have provider observations before their frozen
analysis start. Those rows remain in the immutable raw dataset, but the
year-specific universe excludes them from the study.

## Continuity policy

`predecessor_continuity` tickers require manual verification that Yahoo's
backfilled series represents the same economic equity claim and has continuous
adjustments.

Frozen cases:

```text
DINO <- HFC
PAG  <- UAG
BKNG <- PCLN
```

`current_public_era` histories may contain earlier provider data. Those earlier
rows are not automatically admitted.

## Expected first diagnostic finding

The Phase 1B production data showed that Yahoo's current EXPE history begins on
2005-07-21, while the Phase 1A universe currently admits EXPE from 2000. The
first Phase 1C run is therefore expected to fail and preserve evidence for the
eligibility correction.

The audit reports both:

- first year with a complete ±20 event window;
- first year with both a complete event window and 126 estimation sessions.

This allows the project to distinguish event-window usability from the more
conservative market-model requirement.

## Status rules

```text
FAIL               one or more critical issue rows
PASS_WITH_WARNINGS zero critical, one or more warning rows
PASS               zero critical and zero warning rows
```

The number of issue rows and the `count` within each row are separate. A single
issue row may summarize many affected sessions.

## First-run procedure

Run the diagnostic with:

```powershell
python -m labor_day.audit_prices --allow-critical
```

`--allow-critical` changes only whether the command raises after writing a
failed audit. It does not change issue severity or manifest status.

After correcting any eligibility defect, regenerate the Phase 1A universe panel,
rerun Phase 1B from the verified cache so its manifest receives the new universe
hash, and rerun Phase 1C without `--allow-critical`.
