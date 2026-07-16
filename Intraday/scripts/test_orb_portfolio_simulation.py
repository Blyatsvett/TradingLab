import pandas as pd

from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_MAX_OPENING_RANGE,
    ORB_MIN_GAP,
    ORB_R_MULTIPLE,
)
from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.orb_strategy import (
    build_orb_trades,
    load_intraday_prices,
)
from Intraday.core.paths import DATA_DIR


TICKERS = ORB_ALLOWED_TICKERS

INITIAL_CAPITAL = ORB_INITIAL_CAPITAL
COST_PER_TRADE = ORB_COST_PER_TRADE

BREAKOUT_START = ORB_BREAKOUT_START
BREAKOUT_END = ORB_BREAKOUT_END
R_MULTIPLE = ORB_R_MULTIPLE
MAX_OPENING_RANGE = ORB_MAX_OPENING_RANGE
MIN_GAP = ORB_MIN_GAP

SAME_BAR_PRIORITY = "STOP"

# Portfolio research follows the historical backtest convention:
# use the final available bar of the day for EOD closes.
# Paper trading uses "16:30", but backtest/portfolio research uses None.
EOD_EXIT_TIME = None

SCENARIOS = [1, 2, 3, 5]

OUTPUT_FILE = DATA_DIR / "orb_portfolio_simulation.csv"

# Compatibility aliases. These are updated with the production max-open-position scenario.
PORTFOLIO_TRADES_ALIAS = DATA_DIR / "orb_portfolio_trades_max.csv"
PORTFOLIO_EQUITY_ALIAS = DATA_DIR / "orb_portfolio_equity_max.csv"


SHARED_TO_PORTFOLIO_EXIT_REASON = {
    "STOP_HIT": "stop",
    "TARGET_HIT": "target",
    "CLOSED_EOD": "close",
}


SUMMARY_COLUMNS = [
    "scenario",
    "max_positions",
    "trades_taken",
    "final_equity",
    "total_return",
    "win_rate",
    "avg_trade",
    "profit_factor",
    "max_drawdown",
]


def normalise_prices(df: pd.DataFrame) -> pd.DataFrame:
    prices = df.copy()

    required_columns = [
        "ticker",
        "datetime",
        "high",
        "low",
        "close",
    ]

    for column in required_columns:
        if column not in prices.columns:
            raise ValueError(f"Intraday prices missing required column: {column}")

    prices["ticker"] = prices["ticker"].astype(str)
    prices["datetime"] = pd.to_datetime(prices["datetime"], errors="coerce")

    for column in ["high", "low", "close"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")

    prices = prices.dropna(
        subset=[
            "ticker",
            "datetime",
            "high",
            "low",
            "close",
        ]
    )

    prices = prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    return prices


def reexecute_trade_with_shared_engine(
    trade: pd.Series,
    prices: pd.DataFrame,
) -> dict:
    ticker = str(trade["ticker"])
    entry_time = pd.to_datetime(trade["entry_time"], errors="coerce")

    if pd.isna(entry_time):
        raise ValueError(f"Invalid entry_time for ticker={ticker}: {trade['entry_time']}")

    bars = prices[
        (prices["ticker"] == ticker)
        & (prices["datetime"].dt.date == entry_time.date())
    ].copy()

    if bars.empty:
        raise ValueError(
            f"No intraday bars found for ticker={ticker}, date={entry_time.date()}"
        )

    result = execute_long_orb_trade(
        entry_time=entry_time,
        entry_price=float(trade["entry_price"]),
        stop_price=float(trade["stop_price"]),
        target_price=float(trade["target_price"]),
        bars=bars,
        timestamp_col="datetime",
        close_if_no_hit=True,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
    )

    if result.status != "CLOSED":
        raise ValueError(
            "Shared execution engine did not close portfolio trade: "
            f"ticker={ticker}, entry_time={entry_time}, reason={result.exit_reason}"
        )

    portfolio_exit_reason = SHARED_TO_PORTFOLIO_EXIT_REASON.get(
        result.exit_reason,
        result.exit_reason,
    )

    return {
        "exit_time": result.exit_time,
        "exit_price": result.exit_price,
        "exit_reason": portfolio_exit_reason,
        "gross_return": result.pnl_pct,
        "net_return": result.pnl_pct - COST_PER_TRADE,
    }


def reexecute_trades_with_shared_engine(
    trades: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    trades = trades.copy()

    changed_exit_count = 0

    for idx, trade in trades.iterrows():
        original_exit_reason = str(trade.get("exit_reason", ""))
        original_exit_price = pd.to_numeric(
            trade.get("exit_price", 0),
            errors="coerce",
        )

        execution = reexecute_trade_with_shared_engine(
            trade=trade,
            prices=prices,
        )

        trades.loc[idx, "exit_time"] = execution["exit_time"]
        trades.loc[idx, "exit_price"] = execution["exit_price"]
        trades.loc[idx, "exit_reason"] = execution["exit_reason"]
        trades.loc[idx, "gross_return"] = execution["gross_return"]
        trades.loc[idx, "net_return"] = execution["net_return"]

        new_exit_reason = str(execution["exit_reason"])
        new_exit_price = float(execution["exit_price"])

        if (
            original_exit_reason != new_exit_reason
            or pd.isna(original_exit_price)
            or abs(float(original_exit_price) - new_exit_price) > 0.01
        ):
            changed_exit_count += 1

    print(f"Candidate trades re-executed with shared engine: {len(trades)}")
    print(f"Trades with changed exit reason/price vs old builder output: {changed_exit_count}")

    return trades


def simulate_portfolio(
    trades: pd.DataFrame,
    max_positions: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = trades.copy()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")
    trades["net_return"] = pd.to_numeric(trades["net_return"], errors="coerce")

    trades = trades.dropna(
        subset=[
            "entry_time",
            "exit_time",
            "net_return",
        ]
    )

    trades = trades.sort_values("entry_time").reset_index(drop=True)

    equity = INITIAL_CAPITAL
    open_positions = []
    closed_trades = []
    equity_curve = []

    for _, trade in trades.iterrows():
        entry_time = trade["entry_time"]

        still_open = []

        for pos in open_positions:
            if pos["exit_time"] <= entry_time:
                pnl = pos["position_size_sek"] * pos["net_return"]
                equity += pnl

                pos["pnl_sek"] = pnl
                pos["equity_after_trade"] = equity
                closed_trades.append(pos)

                equity_curve.append(
                    {
                        "trade_number": len(closed_trades),
                        "time": pos["exit_time"],
                        "ticker": pos["ticker"],
                        "pnl_sek": pnl,
                        "equity": equity,
                    }
                )
            else:
                still_open.append(pos)

        open_positions = still_open

        if len(open_positions) < max_positions:
            new_position = trade.to_dict()

            # Position size is locked at entry time.
            # This avoids lookahead bias from sizing at exit.
            new_position["position_size_sek"] = equity / max_positions
            new_position["max_positions"] = max_positions

            open_positions.append(new_position)

    for pos in sorted(open_positions, key=lambda x: x["exit_time"]):
        pnl = pos["position_size_sek"] * pos["net_return"]
        equity += pnl

        pos["pnl_sek"] = pnl
        pos["equity_after_trade"] = equity
        closed_trades.append(pos)

        equity_curve.append(
            {
                "trade_number": len(closed_trades),
                "time": pos["exit_time"],
                "ticker": pos["ticker"],
                "pnl_sek": pnl,
                "equity": equity,
            }
        )

    closed_df = pd.DataFrame(closed_trades)
    equity_df = pd.DataFrame(equity_curve)

    if not closed_df.empty:
        closed_df = closed_df.reset_index(drop=True)
        closed_df["portfolio_trade_number"] = closed_df.index + 1

    if not equity_df.empty:
        equity_df = add_equity_curve_fields(equity_df)

    return closed_df, equity_df


def add_equity_curve_fields(equity_df: pd.DataFrame) -> pd.DataFrame:
    equity_df = equity_df.copy().reset_index(drop=True)

    equity_df["time"] = pd.to_datetime(equity_df["time"], errors="coerce")
    equity_df = equity_df.sort_values("trade_number").reset_index(drop=True)

    equity_df["rolling_peak"] = equity_df["equity"].cummax().clip(
        lower=INITIAL_CAPITAL
    )
    equity_df["drawdown_sek"] = equity_df["equity"] - equity_df["rolling_peak"]
    equity_df["drawdown_pct"] = equity_df["equity"] / equity_df["rolling_peak"] - 1

    return equity_df


def max_drawdown(equity_df: pd.DataFrame) -> float | None:
    if equity_df.empty:
        return None

    if "drawdown_pct" in equity_df.columns:
        return equity_df["drawdown_pct"].min()

    rolling_peak = equity_df["equity"].cummax().clip(lower=INITIAL_CAPITAL)
    drawdown = equity_df["equity"] / rolling_peak - 1

    return drawdown.min()


def summarize(
    label: int,
    closed_df: pd.DataFrame,
    equity_df: pd.DataFrame,
) -> dict | None:
    if closed_df.empty or equity_df.empty:
        return None

    final_equity = equity_df["equity"].iloc[-1]
    total_return = final_equity / INITIAL_CAPITAL - 1
    win_rate = (closed_df["net_return"] > 0).mean()
    avg_trade = closed_df["net_return"].mean()
    dd = max_drawdown(equity_df)

    gross_profit = closed_df.loc[closed_df["pnl_sek"] > 0, "pnl_sek"].sum()
    gross_loss = abs(closed_df.loc[closed_df["pnl_sek"] < 0, "pnl_sek"].sum())

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    return {
        "scenario": label,
        "max_positions": label,
        "trades_taken": len(closed_df),
        "final_equity": final_equity,
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_trade": avg_trade,
        "profit_factor": profit_factor,
        "max_drawdown": dd,
    }


def save_scenario_outputs(
    max_positions: int,
    closed_df: pd.DataFrame,
    equity_df: pd.DataFrame,
) -> None:
    closed_file = DATA_DIR / f"orb_portfolio_trades_max_{max_positions}.csv"
    equity_file = DATA_DIR / f"orb_portfolio_equity_max_{max_positions}.csv"

    closed_df.to_csv(closed_file, index=False)
    equity_df.to_csv(equity_file, index=False)

    if max_positions == ORB_MAX_OPEN_POSITIONS:
        closed_df.to_csv(PORTFOLIO_TRADES_ALIAS, index=False)
        equity_df.to_csv(PORTFOLIO_EQUITY_ALIAS, index=False)

        print(f"Updated production scenario alias -> {PORTFOLIO_TRADES_ALIAS}")
        print(f"Updated production scenario alias -> {PORTFOLIO_EQUITY_ALIAS}")


def main() -> None:
    print("\n=== ORB PORTFOLIO SIMULATION — SHARED EXECUTION ENGINE ===")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Breakout window: {BREAKOUT_START} to {BREAKOUT_END}")
    print(f"R multiple: {R_MULTIPLE}")
    print(f"Max opening range: {MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {MIN_GAP:.2%}")
    print(f"Cost per trade: {COST_PER_TRADE:.4%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")
    print(f"Production max open positions: {ORB_MAX_OPEN_POSITIONS}")

    prices = normalise_prices(load_intraday_prices())

    trades = build_orb_trades(
        df=prices,
        allowed_tickers=TICKERS,
        breakout_start=BREAKOUT_START,
        breakout_end=BREAKOUT_END,
        r_multiple=R_MULTIPLE,
        max_opening_range=MAX_OPENING_RANGE,
        min_gap=MIN_GAP,
        cost_per_trade=COST_PER_TRADE,
    )

    if trades.empty:
        print("No trades found.")
        return

    trades = trades.sort_values("entry_time").reset_index(drop=True)
    trades["candidate_trade_number"] = trades.index + 1

    trades = reexecute_trades_with_shared_engine(
        trades=trades,
        prices=prices,
    )

    results = []

    for max_positions in SCENARIOS:
        closed_df, equity_df = simulate_portfolio(
            trades=trades,
            max_positions=max_positions,
        )

        result = summarize(
            label=max_positions,
            closed_df=closed_df,
            equity_df=equity_df,
        )

        if result is not None:
            results.append(result)

        save_scenario_outputs(
            max_positions=max_positions,
            closed_df=closed_df,
            equity_df=equity_df,
        )

        print(f"\n--- MAX POSITIONS: {max_positions} ---")
        print(f"Trades taken : {len(closed_df)}")

        if not equity_df.empty:
            print(f"Final equity : {equity_df['equity'].iloc[-1]:.2f}")
            print(f"Max drawdown : {equity_df['drawdown_pct'].min():.2%}")
        else:
            print("Final equity : N/A")
            print("Max drawdown : N/A")

    results_df = pd.DataFrame(results)

    for column in SUMMARY_COLUMNS:
        if column not in results_df.columns:
            results_df[column] = 0

    results_df = results_df[SUMMARY_COLUMNS]
    results_df.to_csv(OUTPUT_FILE, index=False)

    print("\n=== PORTFOLIO SIMULATION SUMMARY ===")
    print(results_df.to_string(index=False))

    print(f"\nSaved summary -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()