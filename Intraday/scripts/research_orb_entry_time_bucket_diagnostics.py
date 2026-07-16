import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_MAX_OPENING_RANGE,
    ORB_MIN_GAP,
    ORB_POSITION_SIZE,
    ORB_R_MULTIPLE,
)
from Intraday.core.orb_research import (
    build_research_trades,
    load_normalised_intraday_prices,
)
from Intraday.core.paths import DATA_DIR


OUTPUT_BUCKET_DIAGNOSTICS_FILE = DATA_DIR / "orb_entry_time_bucket_diagnostics.csv"
OUTPUT_TICKER_BUCKET_DIAGNOSTICS_FILE = (
    DATA_DIR / "orb_entry_time_bucket_ticker_diagnostics.csv"
)
OUTPUT_TRADES_FILE = DATA_DIR / "orb_entry_time_bucket_trades.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None


def normalise_trade_times(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    if "date" not in trades.columns:
        trades["date"] = trades["entry_time"].dt.strftime("%Y-%m-%d")
    else:
        trades["date"] = pd.to_datetime(trades["date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )

    trades["entry_time_bucket"] = trades["entry_time"].dt.strftime("%H:%M")

    trades["net_return"] = pd.to_numeric(trades["net_return"], errors="coerce")
    trades["gross_return"] = pd.to_numeric(trades["gross_return"], errors="coerce")

    if "gap" in trades.columns:
        trades["gap"] = pd.to_numeric(trades["gap"], errors="coerce")

    if "opening_range_pct" in trades.columns:
        trades["opening_range_pct"] = pd.to_numeric(
            trades["opening_range_pct"],
            errors="coerce",
        )

    return trades


def can_accept_interval(
    accepted_intervals: list[dict],
    candidate_entry,
    candidate_exit,
    max_positions: int,
) -> bool:
    candidate_entry = pd.to_datetime(candidate_entry)
    candidate_exit = pd.to_datetime(candidate_exit)

    events = []

    for interval in accepted_intervals:
        events.append((pd.to_datetime(interval["entry_time"]), 1))
        events.append((pd.to_datetime(interval["exit_time"]), -1))

    events.append((candidate_entry, 1))
    events.append((candidate_exit, -1))

    # At identical timestamps, close before opening.
    events = sorted(events, key=lambda x: (x[0], x[1]))

    active = 0
    max_active = 0

    for _, change in events:
        active += change
        max_active = max(max_active, active)

    return max_active <= max_positions


def select_earliest_trades_with_capacity(
    trades: pd.DataFrame,
    max_positions: int,
) -> pd.DataFrame:
    trades = normalise_trade_times(trades)

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

        # Pure production-style baseline:
        # earliest entry first, ticker only used as stable deterministic tie-breaker.
        day_trades = day_trades.sort_values(
            ["entry_time", "ticker"],
            ascending=[True, True],
        )

        accepted_intervals = []
        selection_rank = 0

        for _, trade in day_trades.iterrows():
            can_accept = can_accept_interval(
                accepted_intervals=accepted_intervals,
                candidate_entry=trade["entry_time"],
                candidate_exit=trade["exit_time"],
                max_positions=max_positions,
            )

            if not can_accept:
                continue

            selection_rank += 1

            row = trade.to_dict()
            row["selection_rank"] = selection_rank
            row["max_positions"] = max_positions

            selected_rows.append(row)

            accepted_intervals.append(
                {
                    "entry_time": trade["entry_time"],
                    "exit_time": trade["exit_time"],
                }
            )

    selected = pd.DataFrame(selected_rows)

    if selected.empty:
        return selected

    selected = selected.sort_values("entry_time").reset_index(drop=True)
    selected["selected_trade_number"] = selected.index + 1

    return selected


def calculate_profit_factor(returns: pd.Series) -> float:
    returns = pd.to_numeric(returns, errors="coerce").dropna()

    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()

    if losses == 0:
        if gains > 0:
            return 999.0
        return 0.0

    return float(gains / abs(losses))


def calculate_exit_counts(trades: pd.DataFrame) -> dict:
    exit_reasons = trades["exit_reason"].astype(str).str.lower()

    return {
        "target_count": int((exit_reasons == "target").sum()),
        "stop_count": int((exit_reasons == "stop").sum()),
        "close_count": int((exit_reasons == "close").sum()),
        "other_exit_count": int(
            (~exit_reasons.isin(["target", "stop", "close"])).sum()
        ),
    }


def summarize_trade_group(
    trades: pd.DataFrame,
    trade_set: str,
    entry_time_bucket: str,
    ticker: str | None = None,
) -> dict:
    trades = trades.copy()
    returns = pd.to_numeric(trades["net_return"], errors="coerce").dropna()

    exit_counts = calculate_exit_counts(trades)

    winners = int((returns > 0).sum())
    losers = int((returns < 0).sum())
    flat = int((returns == 0).sum())

    row = {
        "trade_set": trade_set,
        "entry_time_bucket": entry_time_bucket,
        "ticker": ticker or "ALL",
        "trades": int(len(trades)),
        "unique_dates": int(trades["date"].nunique()),
        "first_date": trades["date"].min(),
        "last_date": trades["date"].max(),
        "winners": winners,
        "losers": losers,
        "flat": flat,
        "win_rate": float(winners / len(returns)) if len(returns) > 0 else 0.0,
        "avg_trade": float(returns.mean()) if len(returns) > 0 else 0.0,
        "median_trade": float(returns.median()) if len(returns) > 0 else 0.0,
        "best_trade": float(returns.max()) if len(returns) > 0 else 0.0,
        "worst_trade": float(returns.min()) if len(returns) > 0 else 0.0,
        "total_net_return": float(returns.sum()) if len(returns) > 0 else 0.0,
        "estimated_account_contribution": (
            float(returns.sum()) * ORB_POSITION_SIZE if len(returns) > 0 else 0.0
        ),
        "profit_factor": calculate_profit_factor(returns),
        "avg_gap": (
            float(pd.to_numeric(trades["gap"], errors="coerce").mean())
            if "gap" in trades.columns
            else 0.0
        ),
        "avg_opening_range_pct": (
            float(
                pd.to_numeric(
                    trades["opening_range_pct"],
                    errors="coerce",
                ).mean()
            )
            if "opening_range_pct" in trades.columns
            else 0.0
        ),
    }

    row.update(exit_counts)

    return row


def build_bucket_diagnostics(
    trades: pd.DataFrame,
    trade_set: str,
) -> pd.DataFrame:
    rows = []

    for entry_time_bucket, bucket_trades in trades.groupby("entry_time_bucket"):
        rows.append(
            summarize_trade_group(
                trades=bucket_trades,
                trade_set=trade_set,
                entry_time_bucket=entry_time_bucket,
                ticker=None,
            )
        )

    diagnostics = pd.DataFrame(rows)

    if diagnostics.empty:
        return diagnostics

    diagnostics = diagnostics.sort_values("entry_time_bucket").reset_index(drop=True)

    return diagnostics


def build_ticker_bucket_diagnostics(
    trades: pd.DataFrame,
    trade_set: str,
) -> pd.DataFrame:
    rows = []

    for (entry_time_bucket, ticker), group in trades.groupby(
        ["entry_time_bucket", "ticker"]
    ):
        rows.append(
            summarize_trade_group(
                trades=group,
                trade_set=trade_set,
                entry_time_bucket=entry_time_bucket,
                ticker=ticker,
            )
        )

    diagnostics = pd.DataFrame(rows)

    if diagnostics.empty:
        return diagnostics

    diagnostics = diagnostics.sort_values(
        ["entry_time_bucket", "ticker"]
    ).reset_index(drop=True)

    return diagnostics


def add_selected_flags(
    candidates: pd.DataFrame,
    selected: pd.DataFrame,
) -> pd.DataFrame:
    candidates = candidates.copy()
    selected = selected.copy()

    candidates["candidate_id"] = (
        candidates["date"].astype(str)
        + "_"
        + candidates["ticker"].astype(str)
        + "_"
        + pd.to_datetime(candidates["entry_time"]).dt.strftime("%H:%M:%S")
    )

    candidates["selected_by_current_logic"] = False
    candidates["selection_rank"] = 0

    if selected.empty:
        return candidates

    selected["candidate_id"] = (
        selected["date"].astype(str)
        + "_"
        + selected["ticker"].astype(str)
        + "_"
        + pd.to_datetime(selected["entry_time"]).dt.strftime("%H:%M:%S")
    )

    rank_map = dict(
        zip(
            selected["candidate_id"],
            selected["selection_rank"],
        )
    )

    candidates["selected_by_current_logic"] = candidates["candidate_id"].isin(
        rank_map.keys()
    )
    candidates["selection_rank"] = (
        candidates["candidate_id"].map(rank_map).fillna(0).astype(int)
    )

    return candidates


def main() -> None:
    print("\n=== ORB ENTRY TIME BUCKET DIAGNOSTICS ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    candidate_trades = build_research_trades(
        prices=prices,
        allowed_tickers=ORB_ALLOWED_TICKERS,
        breakout_start=ORB_BREAKOUT_START,
        breakout_end=ORB_BREAKOUT_END,
        r_multiple=ORB_R_MULTIPLE,
        max_opening_range=ORB_MAX_OPENING_RANGE,
        min_gap=ORB_MIN_GAP,
        cost_per_trade=ORB_COST_PER_TRADE,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
        verbose=True,
    )

    if candidate_trades.empty:
        print("No candidate trades found.")
        return

    candidate_trades = normalise_trade_times(candidate_trades)
    candidate_trades = candidate_trades.sort_values("entry_time").reset_index(drop=True)
    candidate_trades["candidate_number"] = candidate_trades.index + 1

    selected_trades = select_earliest_trades_with_capacity(
        trades=candidate_trades,
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    candidate_trades = add_selected_flags(
        candidates=candidate_trades,
        selected=selected_trades,
    )

    candidate_trades["trade_set"] = "candidate_all"

    if not selected_trades.empty:
        selected_trades = normalise_trade_times(selected_trades)
        selected_trades["trade_set"] = "selected_current_logic"

    bucket_diagnostics_frames = [
        build_bucket_diagnostics(
            trades=candidate_trades,
            trade_set="candidate_all",
        )
    ]

    ticker_bucket_diagnostics_frames = [
        build_ticker_bucket_diagnostics(
            trades=candidate_trades,
            trade_set="candidate_all",
        )
    ]

    if not selected_trades.empty:
        bucket_diagnostics_frames.append(
            build_bucket_diagnostics(
                trades=selected_trades,
                trade_set="selected_current_logic",
            )
        )

        ticker_bucket_diagnostics_frames.append(
            build_ticker_bucket_diagnostics(
                trades=selected_trades,
                trade_set="selected_current_logic",
            )
        )

    bucket_diagnostics = pd.concat(
        bucket_diagnostics_frames,
        ignore_index=True,
    )

    ticker_bucket_diagnostics = pd.concat(
        ticker_bucket_diagnostics_frames,
        ignore_index=True,
    )

    trade_output = candidate_trades.copy()

    export_csv_for_power_bi(bucket_diagnostics, OUTPUT_BUCKET_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(
        ticker_bucket_diagnostics,
        OUTPUT_TICKER_BUCKET_DIAGNOSTICS_FILE,
    )
    export_csv_for_power_bi(trade_output, OUTPUT_TRADES_FILE)

    print("\n=== ENTRY TIME BUCKET DIAGNOSTICS: SELECTED CURRENT LOGIC ===")

    display_columns = [
        "entry_time_bucket",
        "trades",
        "unique_dates",
        "win_rate",
        "avg_trade",
        "total_net_return",
        "estimated_account_contribution",
        "profit_factor",
        "target_count",
        "stop_count",
        "close_count",
    ]

    selected_bucket = bucket_diagnostics[
        bucket_diagnostics["trade_set"] == "selected_current_logic"
    ].copy()

    print(selected_bucket[display_columns].to_string(index=False))

    print("\n=== ENTRY TIME BUCKET DIAGNOSTICS: ALL CANDIDATES ===")

    candidate_bucket = bucket_diagnostics[
        bucket_diagnostics["trade_set"] == "candidate_all"
    ].copy()

    print(candidate_bucket[display_columns].to_string(index=False))

    print("\n=== TICKER/TIME BUCKET DIAGNOSTICS: SELECTED CURRENT LOGIC ===")

    ticker_display_columns = [
        "entry_time_bucket",
        "ticker",
        "trades",
        "win_rate",
        "avg_trade",
        "total_net_return",
        "profit_factor",
        "target_count",
        "stop_count",
        "close_count",
    ]

    selected_ticker_bucket = ticker_bucket_diagnostics[
        ticker_bucket_diagnostics["trade_set"] == "selected_current_logic"
    ].copy()

    print(selected_ticker_bucket[ticker_display_columns].to_string(index=False))

    print(f"\nSaved bucket diagnostics        -> {OUTPUT_BUCKET_DIAGNOSTICS_FILE}")
    print(f"Saved ticker bucket diagnostics -> {OUTPUT_TICKER_BUCKET_DIAGNOSTICS_FILE}")
    print(f"Saved trade output              -> {OUTPUT_TRADES_FILE}")


if __name__ == "__main__":
    main()