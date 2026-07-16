import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
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


OUTPUT_DIAGNOSTICS_FILE = DATA_DIR / "orb_ticker_window_diagnostics.csv"
OUTPUT_RECOMMENDATIONS_FILE = DATA_DIR / "orb_ticker_window_recommendations.csv"
OUTPUT_TRADES_FILE = DATA_DIR / "orb_ticker_window_trades.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

BREAKOUT_WINDOWS = [
    ("09:35", "10:00"),
    ("09:35", "10:15"),
    ("09:35", "10:30"),
    ("09:35", "10:45"),
    ("09:35", "11:00"),
]

CURRENT_WINDOW_LABEL = f"{ORB_BREAKOUT_START}-{ORB_BREAKOUT_END}"

# Guardrails.
# These do NOT make a production decision. They only classify research candidates.
MIN_TRADES_FOR_RESEARCH_CANDIDATE = 8
MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE = 0.0010  # 0.10% account return


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


def summarize_trade_set(
    trades: pd.DataFrame,
    ticker: str,
    breakout_start: str,
    breakout_end: str,
) -> tuple[dict, pd.DataFrame]:
    window_label = f"{breakout_start}-{breakout_end}"

    empty_summary = {
        "ticker": ticker,
        "breakout_start": breakout_start,
        "breakout_end": breakout_end,
        "window_label": window_label,
        "window_minutes": minutes_between(breakout_start, breakout_end),
        "is_current_config": window_label == CURRENT_WINDOW_LABEL,
        "trades": 0,
        "unique_dates": 0,
        "first_date": "",
        "last_date": "",
        "final_equity": ORB_INITIAL_CAPITAL,
        "total_return": 0.0,
        "win_rate": 0.0,
        "avg_trade": 0.0,
        "max_drawdown": 0.0,
        "profit_factor": 0.0,
        "target_count": 0,
        "stop_count": 0,
        "close_count": 0,
        "other_exit_count": 0,
        "avg_entry_time_minutes": 0.0,
        "avg_gap": 0.0,
        "avg_opening_range_pct": 0.0,
    }

    if trades.empty:
        return empty_summary, pd.DataFrame()

    trades = normalise_trade_times(trades)
    trades = trades.sort_values("entry_time").reset_index(drop=True)
    trades["trade_number"] = trades.index + 1

    trades_with_equity, equity_curve = simulate_orb_equity(
        trades,
        initial_capital=ORB_INITIAL_CAPITAL,
        position_size=ORB_POSITION_SIZE,
    )

    equity_curve = add_equity_curve_fields(
        equity_curve=equity_curve,
        initial_capital=ORB_INITIAL_CAPITAL,
    )

    summary = summarize_research_backtest(
        trades=trades_with_equity,
        equity_curve=equity_curve,
        initial_capital=ORB_INITIAL_CAPITAL,
    )

    if summary is None:
        return empty_summary, pd.DataFrame()

    exit_reasons = trades_with_equity["exit_reason"].astype(str).str.lower()

    entry_minutes = (
        trades_with_equity["entry_time"].dt.hour * 60
        + trades_with_equity["entry_time"].dt.minute
    )

    summary_row = {
        "ticker": ticker,
        "breakout_start": breakout_start,
        "breakout_end": breakout_end,
        "window_label": window_label,
        "window_minutes": minutes_between(breakout_start, breakout_end),
        "is_current_config": window_label == CURRENT_WINDOW_LABEL,
        "trades": summary["trades"],
        "unique_dates": int(trades_with_equity["date"].nunique()),
        "first_date": trades_with_equity["date"].min(),
        "last_date": trades_with_equity["date"].max(),
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
        "target_count": int((exit_reasons == "target").sum()),
        "stop_count": int((exit_reasons == "stop").sum()),
        "close_count": int((exit_reasons == "close").sum()),
        "other_exit_count": int(
            (~exit_reasons.isin(["target", "stop", "close"])).sum()
        ),
        "avg_entry_time_minutes": float(entry_minutes.mean()),
        "avg_gap": (
            float(pd.to_numeric(trades_with_equity["gap"], errors="coerce").mean())
            if "gap" in trades_with_equity.columns
            else 0.0
        ),
        "avg_opening_range_pct": (
            float(
                pd.to_numeric(
                    trades_with_equity["opening_range_pct"],
                    errors="coerce",
                ).mean()
            )
            if "opening_range_pct" in trades_with_equity.columns
            else 0.0
        ),
    }

    trades_with_equity["ticker_window_label"] = ticker + "_" + window_label
    trades_with_equity["breakout_start"] = breakout_start
    trades_with_equity["breakout_end"] = breakout_end
    trades_with_equity["window_label"] = window_label
    trades_with_equity["window_minutes"] = minutes_between(
        breakout_start,
        breakout_end,
    )
    trades_with_equity["is_current_config"] = window_label == CURRENT_WINDOW_LABEL

    return summary_row, trades_with_equity


def add_current_config_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    diagnostics = diagnostics.copy()

    baseline = diagnostics[diagnostics["is_current_config"]][
        [
            "ticker",
            "window_label",
            "trades",
            "final_equity",
            "total_return",
            "win_rate",
            "profit_factor",
            "max_drawdown",
        ]
    ].rename(
        columns={
            "window_label": "current_window_label",
            "trades": "current_trades",
            "final_equity": "current_final_equity",
            "total_return": "current_total_return",
            "win_rate": "current_win_rate",
            "profit_factor": "current_profit_factor",
            "max_drawdown": "current_max_drawdown",
        }
    )

    diagnostics = diagnostics.merge(
        baseline,
        on="ticker",
        how="left",
    )

    diagnostics["excess_return_vs_current"] = (
        diagnostics["total_return"] - diagnostics["current_total_return"]
    )

    diagnostics["excess_equity_vs_current"] = (
        diagnostics["final_equity"] - diagnostics["current_final_equity"]
    )

    diagnostics["beats_current_config"] = diagnostics["excess_return_vs_current"] > 0

    diagnostics["enough_trades_for_research_candidate"] = (
        diagnostics["trades"] >= MIN_TRADES_FOR_RESEARCH_CANDIDATE
    )

    diagnostics["materially_beats_current"] = (
        diagnostics["excess_return_vs_current"]
        >= MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE
    )

    diagnostics["research_candidate"] = (
        diagnostics["enough_trades_for_research_candidate"]
        & diagnostics["materially_beats_current"]
        & (~diagnostics["is_current_config"])
    )

    diagnostics = diagnostics.sort_values(
        ["ticker", "total_return", "profit_factor", "trades"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)

    diagnostics["ticker_window_rank"] = (
        diagnostics.groupby("ticker").cumcount() + 1
    )

    return diagnostics


def build_recommendations(diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for ticker, ticker_rows in diagnostics.groupby("ticker"):
        ticker_rows = ticker_rows.copy()

        best = ticker_rows.sort_values(
            ["total_return", "profit_factor", "trades"],
            ascending=[False, False, False],
        ).iloc[0]

        current = ticker_rows[ticker_rows["is_current_config"]].iloc[0]

        if best["is_current_config"]:
            action = "KEEP_CURRENT"
            reason = "Current 09:35-11:00 window is best for this ticker in-sample."

        elif best["trades"] < MIN_TRADES_FOR_RESEARCH_CANDIDATE:
            action = "LOW_SAMPLE_KEEP_CURRENT"
            reason = (
                "Best alternative has too few trades to trust. "
                "Keep current window."
            )

        elif best["excess_return_vs_current"] < MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE:
            action = "TINY_EDGE_KEEP_CURRENT"
            reason = (
                "Best alternative beats current only slightly. "
                "Not enough edge to justify changing live rules."
            )

        else:
            action = "RESEARCH_CANDIDATE_MONITOR"
            reason = (
                "Alternative window beats current with enough trades. "
                "Monitor; do not productionize without more data."
            )

        rows.append(
            {
                "ticker": ticker,
                "recommended_action": action,
                "reason": reason,
                "current_window_label": current["window_label"],
                "current_trades": current["trades"],
                "current_total_return": current["total_return"],
                "current_win_rate": current["win_rate"],
                "current_profit_factor": current["profit_factor"],
                "best_window_label": best["window_label"],
                "best_trades": best["trades"],
                "best_total_return": best["total_return"],
                "best_win_rate": best["win_rate"],
                "best_profit_factor": best["profit_factor"],
                "best_max_drawdown": best["max_drawdown"],
                "excess_return_vs_current": best["excess_return_vs_current"],
                "excess_equity_vs_current": best["excess_equity_vs_current"],
                "research_candidate": bool(best["research_candidate"]),
                "min_trades_required": MIN_TRADES_FOR_RESEARCH_CANDIDATE,
                "min_excess_return_required": MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE,
            }
        )

    recommendations = pd.DataFrame(rows)

    recommendations = recommendations.sort_values(
        [
            "research_candidate",
            "excess_return_vs_current",
            "best_total_return",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    return recommendations


def main() -> None:
    print("\n=== ORB TICKER-SPECIFIC BREAKOUT WINDOW DIAGNOSTICS ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Current config window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")
    print(f"Minimum trades for research candidate: {MIN_TRADES_FOR_RESEARCH_CANDIDATE}")
    print(
        "Minimum excess return for research candidate: "
        f"{MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE:.2%}"
    )

    prices = load_normalised_intraday_prices()

    summary_rows = []
    trade_frames = []

    for ticker in ORB_ALLOWED_TICKERS:
        print(f"\n=== Testing ticker {ticker} ===")

        for breakout_start, breakout_end in BREAKOUT_WINDOWS:
            window_label = f"{breakout_start}-{breakout_end}"

            print(f"--- Window {window_label} ---")

            candidate_trades = build_research_trades(
                prices=prices,
                allowed_tickers=[ticker],
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

            if not candidate_trades.empty:
                candidate_trades = normalise_trade_times(candidate_trades)
                candidate_trades = candidate_trades.sort_values(
                    "entry_time"
                ).reset_index(drop=True)

            summary_row, trades_with_equity = summarize_trade_set(
                trades=candidate_trades,
                ticker=ticker,
                breakout_start=breakout_start,
                breakout_end=breakout_end,
            )

            summary_rows.append(summary_row)

            if not trades_with_equity.empty:
                trade_frames.append(trades_with_equity)

    diagnostics = pd.DataFrame(summary_rows)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_current_config_comparison(diagnostics)
    recommendations = build_recommendations(diagnostics)

    trades_output = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame()
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(recommendations, OUTPUT_RECOMMENDATIONS_FILE)
    export_csv_for_power_bi(trades_output, OUTPUT_TRADES_FILE)

    print("\n=== TICKER WINDOW RECOMMENDATIONS ===")

    recommendation_columns = [
        "ticker",
        "recommended_action",
        "current_window_label",
        "current_trades",
        "current_total_return",
        "best_window_label",
        "best_trades",
        "best_total_return",
        "excess_return_vs_current",
        "research_candidate",
    ]

    print(recommendations[recommendation_columns].to_string(index=False))

    print("\n=== FULL TICKER WINDOW DIAGNOSTICS ===")

    diagnostic_columns = [
        "ticker",
        "window_label",
        "is_current_config",
        "trades",
        "total_return",
        "win_rate",
        "avg_trade",
        "profit_factor",
        "max_drawdown",
        "excess_return_vs_current",
        "beats_current_config",
        "research_candidate",
        "ticker_window_rank",
    ]

    print(diagnostics[diagnostic_columns].to_string(index=False))

    print(f"\nSaved diagnostics     -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved recommendations -> {OUTPUT_RECOMMENDATIONS_FILE}")
    print(f"Saved trades          -> {OUTPUT_TRADES_FILE}")


if __name__ == "__main__":
    main()