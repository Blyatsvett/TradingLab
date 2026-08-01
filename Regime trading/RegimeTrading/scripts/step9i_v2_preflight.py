from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as v2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight the 23-ticker Step 9I V2 shadow router without writing a decision ledger.")
    parser.add_argument("--source-db", type=Path, default=v2.SHADOW_INTRADAY_DB)
    parser.add_argument("--ledger-db", type=Path, default=v2.SHADOW_LEDGER_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = v2.load_shadow_prices(args.source_db)
    if prices.empty:
        raise SystemExit(f"PREFLIGHT FAILED: no bars found at {args.source_db}")

    expected_market = set(v2.REGIME_SOURCE_TICKERS) | set(v2.HOLDOUT_ONLY_TICKERS)
    observed = set(prices["ticker"].astype(str).unique())
    missing_market = sorted(expected_market - observed)
    latest_date = str(prices["date"].astype(str).max())
    latest = prices[prices["date"].astype(str).eq(latest_date)].copy()
    latest_labels = latest.assign(clock=latest["datetime"].dt.strftime("%H:%M"))
    latest_0940 = set(latest_labels[latest_labels["clock"].eq("09:40")]["ticker"].astype(str))
    missing_0940 = sorted(set(v2.TRADING_TICKERS) - latest_0940)

    taxonomy, decisions, coverage = v2.build_morning_decisions(prices, latest_date)
    expected_decisions = len(v2.TRADING_TICKERS) * 8
    full_decision_grid = len(decisions) == expected_decisions and decisions["ticker"].nunique() == 23

    ledger_batches = 0
    if args.ledger_db.exists():
        with closing(sqlite3.connect(args.ledger_db)) as con:
            v2._ensure_ledger_schema(con)
            ledger_batches = int(pd.read_sql_query("SELECT COUNT(*) AS n FROM shadow_decision_batches", con).iloc[0]["n"])

    checks = {
        "29_market_data_tickers_observed": not missing_market,
        "23_tradable_tickers_locked": len(v2.TRADING_TICKERS) == 23 and len(set(v2.TRADING_TICKERS)) == 23,
        "184_decision_rows_reconstructed": full_decision_grid,
        "latest_day_has_all_23_0940_bars": not missing_0940,
        "v2_ledger_empty_before_first_live_day": ledger_batches == 0,
    }

    print("\n=== STEP 9I V2 PRE-FLIGHT — CORE 5 + HOLDOUT 18 ===")
    print(f"Source database        : {args.source_db}")
    print(f"Latest available date  : {latest_date}")
    print(f"Observed market tickers: {len(observed)}/{len(expected_market)} expected")
    print(f"Reconstructed regime   : {taxonomy['primary_regime']} ({float(taxonomy['regime_confidence']):.1%})")
    print(f"Decision grid          : {len(decisions)}/{expected_decisions}")
    print(f"Coverage core/holdout  : {coverage['core_tickers_observed']}/{coverage['holdout_only_tickers_observed']}")
    print(f"Existing V2 batches    : {ledger_batches}")
    if missing_market:
        print(f"Missing market tickers : {', '.join(missing_market)}")
    if missing_0940:
        print(f"Missing 09:40 bars     : {', '.join(missing_0940)}")
    print("\nChecks:")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    if not all(checks.values()):
        raise SystemExit("PREFLIGHT FAILED. Do not attempt a confirmatory morning seal until every check passes.")
    print("\nPREFLIGHT PASS — the 23-ticker V2 shadow router is ready for the next live morning window.")
    print("No decision batch was written and no order was sent.")


if __name__ == "__main__":
    main()
