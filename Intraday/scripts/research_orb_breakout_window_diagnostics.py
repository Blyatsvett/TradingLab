import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_START,
    ORB_BREAKOUT_END,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_MAX_OPENING_RANGE,
    ORB_MIN_GAP,
    ORB_POSITION_SIZE,
    ORB_R_MULTIPLE,
)
from Intraday.core.orb_research import (
    add_equity_curve_fields,
    build_research_trades,
    load_normalised_intraday_prices,
    summarize_research_backtest,
)
from Intraday.core.orb_strategy import simulate_orb_equity
from Intraday.core.paths import DATA_DIR


OUTPUT_WINDOW_SUMMARY_FILE = DATA_DIR / "orb_breakout_window_diagnostics.csv"
OUTPUT_PERIOD_SUMMARY_FILE = DATA_DIR / "orb_breakout_window_period_diagnostics.csv"
OUTPUT_SELECTED_FILE = DATA_DIR / "orb_breakout_window_selected_trades.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_breakout_window_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

# Number of unique trade dates per walk-forward period.
PERIOD_SIZE_DATES = 15

# Production-style tests:
# same start, different allowed final breakout time.
BREAKOUT_WINDOWS = [
    ("09:35", "10:00"),
    ("09:35", "10:15"),
    ("09:35", "10:30"),
    ("09:35", "10:45"),
    ("09:35", "11:00"),
]


def minutes_between(start_time: str, end_time: str) -> int:
    start = pd.to_datetime(f"2000-01-01 {start_time}")
    end = pd.to_datetime(f"2000-01-01 {end_time}")

    return int((end - start).total_seconds() / 60)


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


def summarize_trade_set(
    selected: pd.DataFrame,
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
    breakout_start: str,
    breakout_end: str,
    candidate_trades: int,
) -> tuple[dict | None, pd.DataFrame]:
    if selected.empty:
        return None, pd.DataFrame()

    selected = selected.sort_values("entry_time").reset_index(drop=True)
    selected["trade_number"] = selected.index + 1

    selected_with_equity, equity_curve = simulate_orb_equity(
        selected,
        initial_capital=ORB_INITIAL_CAPITAL,
        position_size=ORB_POSITION_SIZE,
    )

    equity_curve = add_equity_curve_fields(
        equity_curve=equity_curve,
        initial_capital=ORB_INITIAL_CAPITAL,
    )

    summary = summarize_research_backtest(
        trades=selected_with_equity,
        equity_curve=equity_curve,
        initial_capital=ORB_INITIAL_CAPITAL,
    )

    if summary is None:
        return None, pd.DataFrame()

    window_label = f"{breakout_start}-{breakout_end}"

    selected_with_equity["period_type"] = period_type
    selected_with_equity["period_number"] = period_number
    selected_with_equity["period_label"] = period_label
    selected_with_equity["period_start"] = period_start
    selected_with_equity["period_end"] = period_end
    selected_with_equity["breakout_start"] = breakout_start
    selected_with_equity["breakout_end"] = breakout_end
    selected_with_equity["window_label"] = window_label
    selected_with_equity["window_minutes"] = minutes_between(
        breakout_start,
        breakout_end,
    )
    selected_with_equity["is_current_config"] = (
        breakout_start == ORB_BREAKOUT_START and breakout_end == ORB_BREAKOUT_END
    )

    summary_row = {
        "period_type": period_type,
        "period_number": period_number,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "breakout_start": breakout_start,
        "breakout_end": breakout_end,
        "window_label": window_label,
        "window_minutes": minutes_between(breakout_start, breakout_end),
        "is_current_config": (
            breakout_start == ORB_BREAKOUT_START and breakout_end == ORB_BREAKOUT_END
        ),
        "max_positions": ORB_MAX_OPEN_POSITIONS,
        "candidate_trades": candidate_trades,
        "selected_trades": summary["trades"],
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
    }

    return summary_row, selected_with_equity


def assign_periods_by_trade_date(
    all_dates: list[str],
    period_size_dates: int,
) -> dict[str, dict]:
    unique_dates = pd.Series(all_dates).dropna().drop_duplicates().sort_values()
    unique_dates = unique_dates.reset_index(drop=True)

    date_to_period = {}

    for date_index, date_value in enumerate(unique_dates):
        period_number = int(date_index // period_size_dates) + 1
        period_label = f"P{period_number:02d}"

        period_start_index = (period_number - 1) * period_size_dates
        period_end_index = min(
            period_start_index + period_size_dates - 1,
            len(unique_dates) - 1,
        )

        period_start = unique_dates.iloc[period_start_index]
        period_end = unique_dates.iloc[period_end_index]

        date_to_period[date_value] = {
            "period_number": period_number,
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_end,
        }

    return date_to_period


def add_period_columns(
    trades: pd.DataFrame,
    date_to_period: dict[str, dict],
) -> pd.DataFrame:
    trades = trades.copy()

    trades["period_number"] = trades["date"].map(
        lambda value: date_to_period[value]["period_number"]
    )
    trades["period_label"] = trades["date"].map(
        lambda value: date_to_period[value]["period_label"]
    )
    trades["period_start"] = trades["date"].map(
        lambda value: date_to_period[value]["period_start"]
    )
    trades["period_end"] = trades["date"].map(
        lambda value: date_to_period[value]["period_end"]
    )

    return trades


def add_relative_to_current_config(summary: pd.DataFrame) -> pd.DataFrame:
    summary = summary.copy()

    baseline = summary[summary["is_current_config"]][
        [
            "period_type",
            "period_label",
            "total_return",
            "final_equity",
            "profit_factor",
        ]
    ].rename(
        columns={
            "total_return": "current_config_total_return",
            "final_equity": "current_config_final_equity",
            "profit_factor": "current_config_profit_factor",
        }
    )

    summary = summary.merge(
        baseline,
        on=["period_type", "period_label"],
        how="left",
    )

    summary["excess_return_vs_current_config"] = (
        summary["total_return"] - summary["current_config_total_return"]
    )

    summary["excess_equity_vs_current_config"] = (
        summary["final_equity"] - summary["current_config_final_equity"]
    )

    summary["beats_current_config"] = (
        summary["excess_return_vs_current_config"] > 0
    )

    summary["period_best_return"] = summary.groupby(
        ["period_type", "period_label"]
    )["total_return"].transform("max")

    summary["is_period_winner"] = summary["total_return"] == summary["period_best_return"]

    summary = summary.sort_values(
        [
            "period_type",
            "period_number",
            "total_return",
            "profit_factor",
        ],
        ascending=[
            True,
            True,
            False,
            False,
        ],
    ).reset_index(drop=True)

    return summary


def main() -> None:
    print("\n=== ORB BREAKOUT WINDOW DIAGNOSTICS ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Current config window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Walk-forward period size: {PERIOD_SIZE_DATES} unique trade dates")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    all_candidate_frames = []
    all_selected_frames = []
    all_summary_rows = []

    for breakout_start, breakout_end in BREAKOUT_WINDOWS:
        window_label = f"{breakout_start}-{breakout_end}"

        print(f"\n--- Testing breakout window {window_label} ---")

        candidate_trades = build_research_trades(
            prices=prices,
            allowed_tickers=ORB_ALLOWED_TICKERS,
            breakout_start=breakout_start,
            breakout_end=breakout_end,
            r_multiple=ORB_R_MULTIPLE,
            max_opening_range=ORB_MAX_OPENING_RANGE,
            min_gap=ORB_MIN_GAP,
            cost_per_trade=ORB_COST_PER_TRADE,
            same_bar_priority=SAME_BAR_PRIORITY,
            eod_exit_time=EOD_EXIT_TIME,
            verbose=True,
        )

        if candidate_trades.empty:
            print(f"No candidate trades for {window_label}")
            continue

        candidate_trades = normalise_trade_times(candidate_trades)
        candidate_trades = candidate_trades.sort_values("entry_time").reset_index(
            drop=True
        )

        candidate_trades["candidate_number"] = candidate_trades.index + 1
        candidate_trades["breakout_start"] = breakout_start
        candidate_trades["breakout_end"] = breakout_end
        candidate_trades["window_label"] = window_label
        candidate_trades["window_minutes"] = minutes_between(
            breakout_start,
            breakout_end,
        )
        candidate_trades["is_current_config"] = (
            breakout_start == ORB_BREAKOUT_START and breakout_end == ORB_BREAKOUT_END
        )

        selected = select_earliest_trades_with_capacity(
            trades=candidate_trades,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        if selected.empty:
            print(f"No selected trades for {window_label}")
            continue

        selected["breakout_start"] = breakout_start
        selected["breakout_end"] = breakout_end
        selected["window_label"] = window_label
        selected["window_minutes"] = minutes_between(
            breakout_start,
            breakout_end,
        )
        selected["is_current_config"] = (
            breakout_start == ORB_BREAKOUT_START and breakout_end == ORB_BREAKOUT_END
        )

        period_start = selected["date"].min()
        period_end = selected["date"].max()

        whole_summary, selected_with_equity = summarize_trade_set(
            selected=selected,
            period_type="ALL",
            period_number=0,
            period_label="ALL",
            period_start=period_start,
            period_end=period_end,
            breakout_start=breakout_start,
            breakout_end=breakout_end,
            candidate_trades=len(candidate_trades),
        )

        if whole_summary is not None:
            all_summary_rows.append(whole_summary)

        if not selected_with_equity.empty:
            all_selected_frames.append(selected_with_equity)

        all_candidate_frames.append(candidate_trades)

    if not all_candidate_frames:
        print("No candidate trades produced.")
        return

    candidates_all = pd.concat(all_candidate_frames, ignore_index=True)

    all_dates = sorted(candidates_all["date"].dropna().unique())
    date_to_period = assign_periods_by_trade_date(
        all_dates=all_dates,
        period_size_dates=PERIOD_SIZE_DATES,
    )

    candidates_all = add_period_columns(
        trades=candidates_all,
        date_to_period=date_to_period,
    )

    # Period-level summaries.
    for window_label, window_candidates in candidates_all.groupby("window_label"):
        window_candidates = window_candidates.copy()

        breakout_start = window_candidates["breakout_start"].iloc[0]
        breakout_end = window_candidates["breakout_end"].iloc[0]

        selected = select_earliest_trades_with_capacity(
            trades=window_candidates,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        if selected.empty:
            continue

        selected = add_period_columns(
            trades=selected,
            date_to_period=date_to_period,
        )

        for period_number, period_selected in selected.groupby("period_number"):
            period_selected = period_selected.copy()

            period_label = period_selected["period_label"].iloc[0]
            period_start = period_selected["period_start"].iloc[0]
            period_end = period_selected["period_end"].iloc[0]

            period_candidate_count = len(
                window_candidates[
                    window_candidates["period_number"] == period_number
                ]
            )

            period_summary, period_selected_with_equity = summarize_trade_set(
                selected=period_selected,
                period_type="PERIOD",
                period_number=int(period_number),
                period_label=period_label,
                period_start=period_start,
                period_end=period_end,
                breakout_start=breakout_start,
                breakout_end=breakout_end,
                candidate_trades=period_candidate_count,
            )

            if period_summary is not None:
                all_summary_rows.append(period_summary)

            if not period_selected_with_equity.empty:
                all_selected_frames.append(period_selected_with_equity)

    diagnostics = pd.DataFrame(all_summary_rows)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_relative_to_current_config(diagnostics)

    whole_sample = diagnostics[diagnostics["period_type"] == "ALL"].copy()
    period_sample = diagnostics[diagnostics["period_type"] == "PERIOD"].copy()

    selected_all = (
        pd.concat(all_selected_frames, ignore_index=True)
        if all_selected_frames
        else pd.DataFrame()
    )

    export_csv_for_power_bi(whole_sample, OUTPUT_WINDOW_SUMMARY_FILE)
    export_csv_for_power_bi(period_sample, OUTPUT_PERIOD_SUMMARY_FILE)
    export_csv_for_power_bi(selected_all, OUTPUT_SELECTED_FILE)
    export_csv_for_power_bi(candidates_all, OUTPUT_CANDIDATES_FILE)

    print("\n=== WHOLE-SAMPLE BREAKOUT WINDOW RESULTS ===")

    whole_columns = [
        "window_label",
        "is_current_config",
        "candidate_trades",
        "selected_trades",
        "total_return",
        "win_rate",
        "avg_trade",
        "profit_factor",
        "max_drawdown",
        "excess_return_vs_current_config",
        "beats_current_config",
        "is_period_winner",
    ]

    print(
        whole_sample.sort_values(
            ["total_return", "profit_factor"],
            ascending=[False, False],
        )[whole_columns].to_string(index=False)
    )

    print("\n=== WALK-FORWARD PERIOD RESULTS ===")

    period_columns = [
        "period_label",
        "period_start",
        "period_end",
        "window_label",
        "is_current_config",
        "candidate_trades",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "excess_return_vs_current_config",
        "beats_current_config",
        "is_period_winner",
    ]

    print(
        period_sample.sort_values(
            [
                "period_number",
                "total_return",
                "profit_factor",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )[period_columns].to_string(index=False)
    )

    print(f"\nSaved whole-sample diagnostics -> {OUTPUT_WINDOW_SUMMARY_FILE}")
    print(f"Saved period diagnostics       -> {OUTPUT_PERIOD_SUMMARY_FILE}")
    print(f"Saved selected trades          -> {OUTPUT_SELECTED_FILE}")
    print(f"Saved candidate trades         -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()