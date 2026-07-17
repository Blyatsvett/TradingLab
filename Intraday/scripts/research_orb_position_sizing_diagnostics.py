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


OUTPUT_DIAGNOSTICS_FILE = DATA_DIR / "orb_position_sizing_diagnostics.csv"
OUTPUT_TRADES_FILE = DATA_DIR / "orb_position_sizing_trades.csv"
OUTPUT_EQUITY_FILE = DATA_DIR / "orb_position_sizing_equity_curve.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_position_sizing_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

RISK_FILTER_THRESHOLD = 0.0200

BASELINE_SELECTION_SET = "baseline_current_rules"
RISK_FILTER_SELECTION_SET = "shadow_risk_le_2_00pct"

BASELINE_SIZING_MODEL = "fixed_10pct"

POSITION_SIZING_MODELS = [
    {
        "sizing_model": "fixed_5pct",
        "model_type": "fixed",
        "description": "Fixed 5% notional position size.",
        "fixed_position_pct": 0.05,
        "target_account_risk_pct": 0.0,
        "max_position_pct": 0.05,
    },
    {
        "sizing_model": BASELINE_SIZING_MODEL,
        "model_type": "fixed",
        "description": "Fixed 10% notional position size. Current baseline.",
        "fixed_position_pct": ORB_POSITION_SIZE,
        "target_account_risk_pct": 0.0,
        "max_position_pct": ORB_POSITION_SIZE,
    },
    {
        "sizing_model": "fixed_15pct",
        "model_type": "fixed",
        "description": "Fixed 15% notional position size.",
        "fixed_position_pct": 0.15,
        "target_account_risk_pct": 0.0,
        "max_position_pct": 0.15,
    },
    {
        "sizing_model": "risk_target_0_10pct_cap_10pct",
        "model_type": "risk_adjusted",
        "description": (
            "Target 0.10% account risk per trade, capped at 10% notional."
        ),
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0010,
        "max_position_pct": 0.10,
    },
    {
        "sizing_model": "risk_target_0_10pct_cap_15pct",
        "model_type": "risk_adjusted",
        "description": (
            "Target 0.10% account risk per trade, capped at 15% notional."
        ),
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0010,
        "max_position_pct": 0.15,
    },
    {
        "sizing_model": "risk_target_0_10pct_cap_20pct",
        "model_type": "risk_adjusted",
        "description": (
            "Target 0.10% account risk per trade, capped at 20% notional."
        ),
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0010,
        "max_position_pct": 0.20,
    },
    {
        "sizing_model": "risk_target_0_15pct_cap_20pct",
        "model_type": "risk_adjusted",
        "description": (
            "Target 0.15% account risk per trade, capped at 20% notional."
        ),
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0015,
        "max_position_pct": 0.20,
    },
    {
        "sizing_model": "risk_target_0_20pct_cap_20pct",
        "model_type": "risk_adjusted",
        "description": (
            "Target 0.20% account risk per trade, capped at 20% notional."
        ),
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0020,
        "max_position_pct": 0.20,
    },
]

# Research-only guardrails.
MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE = 0.0010
MAX_DRAWDOWN_WORSENING_ALLOWED = 0.0010


def time_to_minutes(time_value: str) -> int:
    timestamp = pd.to_datetime(f"2000-01-01 {time_value}")
    return int(timestamp.hour * 60 + timestamp.minute)


def normalise_trade_data(trades: pd.DataFrame) -> pd.DataFrame:
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
    trades["entry_minutes"] = (
        trades["entry_time"].dt.hour * 60 + trades["entry_time"].dt.minute
    )

    trades["entry_minutes_from_breakout_start"] = (
        trades["entry_minutes"] - time_to_minutes(ORB_BREAKOUT_START)
    )

    numeric_columns = [
        "net_return",
        "gross_return",
        "entry_price",
        "exit_price",
        "stop_price",
        "target_price",
        "gap",
        "opening_range_pct",
    ]

    for column in numeric_columns:
        if column in trades.columns:
            trades[column] = pd.to_numeric(trades[column], errors="coerce")

    if "gap" not in trades.columns:
        trades["gap"] = 0.0

    if "opening_range_pct" not in trades.columns:
        trades["opening_range_pct"] = 0.0

    trades["gap_abs"] = trades["gap"].abs()

    trades["risk_pct"] = (
        (trades["entry_price"] - trades["stop_price"]) / trades["entry_price"]
    )

    trades["target_return_pct"] = (
        (trades["target_price"] - trades["entry_price"]) / trades["entry_price"]
    )

    trades["risk_pct"] = pd.to_numeric(trades["risk_pct"], errors="coerce").fillna(0.0)

    trades["target_return_pct"] = pd.to_numeric(
        trades["target_return_pct"],
        errors="coerce",
    ).fillna(0.0)

    trades["passes_risk_filter"] = trades["risk_pct"] <= RISK_FILTER_THRESHOLD

    trades["trade_key"] = (
        trades["date"].astype(str)
        + "_"
        + trades["ticker"].astype(str)
        + "_"
        + trades["entry_time"].dt.strftime("%H:%M:%S")
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
    selection_set: str,
    max_positions: int,
) -> pd.DataFrame:
    trades = normalise_trade_data(trades)

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

        # Production-style selection:
        # earliest entry first, ticker only used as deterministic tie-breaker.
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
            row["selection_set"] = selection_set
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


def calculate_position_pct(
    trade: pd.Series,
    sizing_model: dict,
) -> tuple[float, float, bool]:
    model_type = sizing_model["model_type"]

    if model_type == "fixed":
        position_pct = float(sizing_model["fixed_position_pct"])
        raw_position_pct = position_pct
        capped_by_max_position_size = False

        return position_pct, raw_position_pct, capped_by_max_position_size

    if model_type != "risk_adjusted":
        raise ValueError(f"Unknown sizing model type: {model_type}")

    risk_pct = float(trade.get("risk_pct", 0.0))

    target_account_risk_pct = float(sizing_model["target_account_risk_pct"])
    max_position_pct = float(sizing_model["max_position_pct"])

    if risk_pct <= 0:
        raw_position_pct = 0.0
    else:
        raw_position_pct = target_account_risk_pct / risk_pct

    position_pct = min(raw_position_pct, max_position_pct)
    position_pct = max(position_pct, 0.0)

    capped_by_max_position_size = raw_position_pct > max_position_pct

    return position_pct, raw_position_pct, capped_by_max_position_size


def calculate_profit_factor_from_pnl(pnl: pd.Series) -> float:
    pnl = pd.to_numeric(pnl, errors="coerce").dropna()

    gains = pnl[pnl > 0].sum()
    losses = pnl[pnl < 0].sum()

    if losses == 0:
        if gains > 0:
            return 999.0
        return 0.0

    return float(gains / abs(losses))


def calculate_exit_counts(trades: pd.DataFrame) -> dict:
    if trades.empty or "exit_reason" not in trades.columns:
        return {
            "target_count": 0,
            "stop_count": 0,
            "close_count": 0,
            "other_exit_count": 0,
        }

    exit_reasons = trades["exit_reason"].astype(str).str.lower()

    return {
        "target_count": int((exit_reasons == "target").sum()),
        "stop_count": int((exit_reasons == "stop").sum()),
        "close_count": int((exit_reasons == "close").sum()),
        "other_exit_count": int(
            (~exit_reasons.isin(["target", "stop", "close"])).sum()
        ),
    }


def simulate_position_sizing(
    selected_trades: pd.DataFrame,
    sizing_model: dict,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    selection_set = (
        selected_trades["selection_set"].iloc[0]
        if not selected_trades.empty and "selection_set" in selected_trades.columns
        else ""
    )

    sizing_model_name = sizing_model["sizing_model"]

    empty_summary = {
        "selection_set": selection_set,
        "sizing_model": sizing_model_name,
        "model_type": sizing_model["model_type"],
        "description": sizing_model["description"],
        "target_account_risk_pct": sizing_model["target_account_risk_pct"],
        "max_position_pct_config": sizing_model["max_position_pct"],
        "selected_trades": 0,
        "first_date": "",
        "last_date": "",
        "final_equity": ORB_INITIAL_CAPITAL,
        "total_return": 0.0,
        "total_pnl_sek": 0.0,
        "win_rate": 0.0,
        "avg_trade_account_return": 0.0,
        "avg_trade_notional_return": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "avg_position_size_pct": 0.0,
        "max_position_size_pct": 0.0,
        "min_position_size_pct": 0.0,
        "avg_position_size_sek": 0.0,
        "avg_estimated_account_risk_pct": 0.0,
        "max_estimated_account_risk_pct": 0.0,
        "avg_trade_risk_pct": 0.0,
        "max_trade_risk_pct": 0.0,
        "capped_trade_count": 0,
        "target_count": 0,
        "stop_count": 0,
        "close_count": 0,
        "other_exit_count": 0,
    }

    if selected_trades.empty:
        return empty_summary, pd.DataFrame(), pd.DataFrame()

    trades = normalise_trade_data(selected_trades)
    trades = trades.sort_values("entry_time").reset_index(drop=True)

    equity = ORB_INITIAL_CAPITAL
    peak_equity = ORB_INITIAL_CAPITAL

    trade_rows = []
    equity_rows = [
        {
            "selection_set": selection_set,
            "sizing_model": sizing_model_name,
            "trade_number": 0,
            "date": "",
            "ticker": "START",
            "entry_time": "",
            "exit_time": "",
            "equity": ORB_INITIAL_CAPITAL,
            "pnl_sek": 0.0,
            "account_return": 0.0,
            "cumulative_return": 0.0,
            "drawdown_pct": 0.0,
            "position_size_pct": 0.0,
            "estimated_account_risk_pct": 0.0,
        }
    ]

    for trade_index, trade in trades.iterrows():
        position_pct, raw_position_pct, capped_by_max_position_size = (
            calculate_position_pct(
                trade=trade,
                sizing_model=sizing_model,
            )
        )

        position_size_sek = ORB_INITIAL_CAPITAL * position_pct

        pnl_sek = position_size_sek * float(trade["net_return"])
        account_return = pnl_sek / ORB_INITIAL_CAPITAL

        equity += pnl_sek
        peak_equity = max(peak_equity, equity)

        drawdown_pct = (equity / peak_equity) - 1.0
        cumulative_return = (equity / ORB_INITIAL_CAPITAL) - 1.0

        estimated_account_risk_pct = position_pct * float(trade["risk_pct"])

        row = trade.to_dict()
        row.update(
            {
                "sizing_model": sizing_model_name,
                "model_type": sizing_model["model_type"],
                "sizing_description": sizing_model["description"],
                "trade_number": trade_index + 1,
                "position_size_pct": position_pct,
                "raw_position_size_pct": raw_position_pct,
                "position_size_sek": position_size_sek,
                "estimated_account_risk_pct": estimated_account_risk_pct,
                "capped_by_max_position_size": capped_by_max_position_size,
                "pnl_sek": pnl_sek,
                "account_return": account_return,
                "equity": equity,
                "cumulative_return": cumulative_return,
                "drawdown_pct": drawdown_pct,
            }
        )

        trade_rows.append(row)

        equity_rows.append(
            {
                "selection_set": selection_set,
                "sizing_model": sizing_model_name,
                "trade_number": trade_index + 1,
                "date": trade["date"],
                "ticker": trade["ticker"],
                "entry_time": trade["entry_time"],
                "exit_time": trade["exit_time"],
                "equity": equity,
                "pnl_sek": pnl_sek,
                "account_return": account_return,
                "cumulative_return": cumulative_return,
                "drawdown_pct": drawdown_pct,
                "position_size_pct": position_pct,
                "estimated_account_risk_pct": estimated_account_risk_pct,
            }
        )

    trades_out = pd.DataFrame(trade_rows)
    equity_curve = pd.DataFrame(equity_rows)

    exit_counts = calculate_exit_counts(trades_out)

    total_pnl_sek = float(trades_out["pnl_sek"].sum())
    total_return = total_pnl_sek / ORB_INITIAL_CAPITAL

    summary = {
        "selection_set": selection_set,
        "sizing_model": sizing_model_name,
        "model_type": sizing_model["model_type"],
        "description": sizing_model["description"],
        "target_account_risk_pct": sizing_model["target_account_risk_pct"],
        "max_position_pct_config": sizing_model["max_position_pct"],
        "selected_trades": int(len(trades_out)),
        "first_date": trades_out["date"].min(),
        "last_date": trades_out["date"].max(),
        "final_equity": float(ORB_INITIAL_CAPITAL + total_pnl_sek),
        "total_return": total_return,
        "total_pnl_sek": total_pnl_sek,
        "win_rate": float((trades_out["pnl_sek"] > 0).mean()),
        "avg_trade_account_return": float(trades_out["account_return"].mean()),
        "avg_trade_notional_return": float(trades_out["net_return"].mean()),
        "profit_factor": calculate_profit_factor_from_pnl(trades_out["pnl_sek"]),
        "max_drawdown": float(equity_curve["drawdown_pct"].min()),
        "avg_position_size_pct": float(trades_out["position_size_pct"].mean()),
        "max_position_size_pct": float(trades_out["position_size_pct"].max()),
        "min_position_size_pct": float(trades_out["position_size_pct"].min()),
        "avg_position_size_sek": float(trades_out["position_size_sek"].mean()),
        "avg_estimated_account_risk_pct": float(
            trades_out["estimated_account_risk_pct"].mean()
        ),
        "max_estimated_account_risk_pct": float(
            trades_out["estimated_account_risk_pct"].max()
        ),
        "avg_trade_risk_pct": float(trades_out["risk_pct"].mean()),
        "max_trade_risk_pct": float(trades_out["risk_pct"].max()),
        "capped_trade_count": int(trades_out["capped_by_max_position_size"].sum()),
    }

    summary.update(exit_counts)

    return summary, trades_out, equity_curve


def add_baseline_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    diagnostics = diagnostics.copy()

    baseline = diagnostics[
        diagnostics["sizing_model"].eq(BASELINE_SIZING_MODEL)
    ][
        [
            "selection_set",
            "total_return",
            "final_equity",
            "total_pnl_sek",
            "profit_factor",
            "max_drawdown",
            "avg_estimated_account_risk_pct",
            "max_estimated_account_risk_pct",
        ]
    ].rename(
        columns={
            "total_return": "baseline_total_return",
            "final_equity": "baseline_final_equity",
            "total_pnl_sek": "baseline_total_pnl_sek",
            "profit_factor": "baseline_profit_factor",
            "max_drawdown": "baseline_max_drawdown",
            "avg_estimated_account_risk_pct": (
                "baseline_avg_estimated_account_risk_pct"
            ),
            "max_estimated_account_risk_pct": (
                "baseline_max_estimated_account_risk_pct"
            ),
        }
    )

    diagnostics = diagnostics.merge(
        baseline,
        on="selection_set",
        how="left",
    )

    diagnostics["excess_return_vs_fixed_10pct"] = (
        diagnostics["total_return"] - diagnostics["baseline_total_return"]
    )

    diagnostics["excess_equity_vs_fixed_10pct"] = (
        diagnostics["final_equity"] - diagnostics["baseline_final_equity"]
    )

    diagnostics["profit_factor_change_vs_fixed_10pct"] = (
        diagnostics["profit_factor"] - diagnostics["baseline_profit_factor"]
    )

    # More negative drawdown is worse.
    diagnostics["drawdown_change_vs_fixed_10pct"] = (
        diagnostics["max_drawdown"] - diagnostics["baseline_max_drawdown"]
    )

    diagnostics["beats_fixed_10pct"] = diagnostics["excess_return_vs_fixed_10pct"] > 0

    diagnostics["materially_beats_fixed_10pct"] = (
        diagnostics["excess_return_vs_fixed_10pct"]
        >= MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE
    )

    diagnostics["drawdown_not_much_worse"] = (
        diagnostics["drawdown_change_vs_fixed_10pct"]
        >= -MAX_DRAWDOWN_WORSENING_ALLOWED
    )

    diagnostics["profit_factor_not_worse"] = (
        diagnostics["profit_factor"] >= diagnostics["baseline_profit_factor"]
    )

    diagnostics["research_candidate"] = (
        diagnostics["model_type"].eq("risk_adjusted")
        & diagnostics["materially_beats_fixed_10pct"]
        & diagnostics["drawdown_not_much_worse"]
        & diagnostics["profit_factor_not_worse"]
    )

    diagnostics = diagnostics.sort_values(
        [
            "selection_set",
            "research_candidate",
            "total_return",
            "profit_factor",
        ],
        ascending=[
            True,
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    diagnostics["rank_within_selection_set"] = (
        diagnostics.groupby("selection_set").cumcount() + 1
    )

    return diagnostics


def main() -> None:
    print("\n=== ORB POSITION SIZING DIAGNOSTICS ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Current fixed position size: {ORB_POSITION_SIZE:.2%}")
    print(f"Shadow risk filter: risk_pct <= {RISK_FILTER_THRESHOLD:.2%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    candidates = build_research_trades(
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

    if candidates.empty:
        print("No candidate trades found.")
        return

    candidates = normalise_trade_data(candidates)
    candidates = candidates.sort_values("entry_time").reset_index(drop=True)
    candidates["candidate_number"] = candidates.index + 1

    baseline_selected = select_earliest_trades_with_capacity(
        trades=candidates,
        selection_set=BASELINE_SELECTION_SET,
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    risk_filter_candidates = candidates[candidates["passes_risk_filter"]].copy()

    risk_filter_selected = select_earliest_trades_with_capacity(
        trades=risk_filter_candidates,
        selection_set=RISK_FILTER_SELECTION_SET,
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    selection_sets = [
        {
            "selection_set": BASELINE_SELECTION_SET,
            "selected_trades": baseline_selected,
        },
        {
            "selection_set": RISK_FILTER_SELECTION_SET,
            "selected_trades": risk_filter_selected,
        },
    ]

    summary_rows = []
    trade_frames = []
    equity_frames = []

    for selection_set_definition in selection_sets:
        selection_set = selection_set_definition["selection_set"]
        selected_trades = selection_set_definition["selected_trades"]

        print(f"\n=== Selection set: {selection_set} ===")
        print(f"Selected trades: {len(selected_trades)}")

        for sizing_model in POSITION_SIZING_MODELS:
            print(f"--- Testing sizing model: {sizing_model['sizing_model']} ---")

            summary, trades_out, equity_curve = simulate_position_sizing(
                selected_trades=selected_trades,
                sizing_model=sizing_model,
            )

            summary_rows.append(summary)

            if not trades_out.empty:
                trade_frames.append(trades_out)

            if not equity_curve.empty:
                equity_frames.append(equity_curve)

            print(f"Total return: {summary['total_return']:.4%}")
            print(f"Final equity: {summary['final_equity']:.2f} SEK")
            print(f"Profit factor: {summary['profit_factor']:.4f}")
            print(f"Max drawdown: {summary['max_drawdown']:.4%}")
            print(f"Avg position size: {summary['avg_position_size_pct']:.2%}")
            print(
                "Avg estimated account risk: "
                f"{summary['avg_estimated_account_risk_pct']:.4%}"
            )

    diagnostics = pd.DataFrame(summary_rows)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_baseline_comparison(diagnostics)

    trades_output = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame()
    )

    equity_output = (
        pd.concat(equity_frames, ignore_index=True)
        if equity_frames
        else pd.DataFrame()
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(trades_output, OUTPUT_TRADES_FILE)
    export_csv_for_power_bi(equity_output, OUTPUT_EQUITY_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_CANDIDATES_FILE)

    print("\n=== POSITION SIZING RESULTS ===")

    display_columns = [
        "selection_set",
        "rank_within_selection_set",
        "sizing_model",
        "model_type",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "avg_position_size_pct",
        "max_position_size_pct",
        "avg_estimated_account_risk_pct",
        "max_estimated_account_risk_pct",
        "excess_return_vs_fixed_10pct",
        "drawdown_change_vs_fixed_10pct",
        "research_candidate",
    ]

    print(diagnostics[display_columns].to_string(index=False))

    print("\n=== RESEARCH CANDIDATES ===")

    research_candidates = diagnostics[diagnostics["research_candidate"]].copy()

    if research_candidates.empty:
        print("No position-sizing model passed the research-candidate guardrails.")
    else:
        print(research_candidates[display_columns].to_string(index=False))

    print(f"\nSaved diagnostics -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved trades      -> {OUTPUT_TRADES_FILE}")
    print(f"Saved equity      -> {OUTPUT_EQUITY_FILE}")
    print(f"Saved candidates  -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()