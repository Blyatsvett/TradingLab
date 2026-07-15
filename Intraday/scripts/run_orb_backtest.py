import pandas as pd

from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.orb_strategy import (
    build_orb_trades,
    load_intraday_prices,
    orb_summary,
    simulate_orb_equity,
)
from Intraday.core.paths import DATA_DIR


ALLOWED_TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "ATCO-A.ST",
    "EVO.ST",
    "SEB-A.ST",
    "ABB.ST",
]

INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10

BREAKOUT_START = "09:35"
BREAKOUT_END = "11:00"
R_MULTIPLE = 1.0
MAX_OPENING_RANGE = 0.02
MIN_GAP = 0.0
COST_PER_TRADE = 0.0005

SAME_BAR_PRIORITY = "STOP"

# Important:
# Paper trading uses EOD_EXIT_TIME = "16:30".
# The historical backtest has always used the final available bar of the day,
# usually around 17:25, so this stays None to preserve current backtest behavior.
EOD_EXIT_TIME = None

BACKTEST_TRADES_FILE = DATA_DIR / "orb_backtest_trades.csv"
BACKTEST_EQUITY_FILE = DATA_DIR / "orb_backtest_equity_curve.csv"


SHARED_TO_BACKTEST_EXIT_REASON = {
    "STOP_HIT": "stop",
    "TARGET_HIT": "target",
    "CLOSED_EOD": "close",
}


OUTPUT_TRADE_COLUMNS = [
    "date",
    "ticker",
    "entry_time",
    "exit_time",
    "exit_reason",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_price",
    "gap",
    "opening_range_pct",
    "gross_return",
    "net_return",
    "trade_number",
    "pnl",
    "equity",
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
            "Shared execution engine did not close backtest trade: "
            f"ticker={ticker}, entry_time={entry_time}, reason={result.exit_reason}"
        )

    backtest_exit_reason = SHARED_TO_BACKTEST_EXIT_REASON.get(
        result.exit_reason,
        result.exit_reason,
    )

    return {
        "exit_time": result.exit_time,
        "exit_price": result.exit_price,
        "exit_reason": backtest_exit_reason,
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

    print(f"Trades re-executed with shared engine: {len(trades)}")
    print(f"Trades with changed exit reason/price vs old builder output: {changed_exit_count}")

    return trades


def add_equity_curve_fields(equity_curve: pd.DataFrame) -> pd.DataFrame:
    equity_curve = equity_curve.copy().reset_index(drop=True)

    equity_curve["trade_number"] = equity_curve.index + 1
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax().clip(
        lower=INITIAL_CAPITAL
    )
    equity_curve["drawdown_sek"] = equity_curve["equity"] - equity_curve["rolling_peak"]
    equity_curve["drawdown_pct"] = (
        equity_curve["equity"] / equity_curve["rolling_peak"] - 1
    )

    return equity_curve


def order_trade_columns(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    for column in OUTPUT_TRADE_COLUMNS:
        if column not in trades.columns:
            trades[column] = 0

    return trades[OUTPUT_TRADE_COLUMNS]


def main() -> None:
    print("\n=== RUNNING ORB BACKTEST ===")
    print("Using shared ORB execution engine for exits.")
    print(f"Tickers: {', '.join(ALLOWED_TICKERS)}")
    print(f"Breakout window: {BREAKOUT_START} to {BREAKOUT_END}")
    print(f"R multiple: {R_MULTIPLE}")
    print(f"Max opening range: {MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {MIN_GAP:.2%}")
    print(f"Cost per trade: {COST_PER_TRADE:.4%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = normalise_prices(load_intraday_prices())

    trades = build_orb_trades(
        df=prices,
        allowed_tickers=ALLOWED_TICKERS,
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
    trades["trade_number"] = trades.index + 1

    trades = reexecute_trades_with_shared_engine(
        trades=trades,
        prices=prices,
    )

    trades, equity_curve = simulate_orb_equity(
        trades,
        initial_capital=INITIAL_CAPITAL,
        position_size=POSITION_SIZE,
    )

    equity_curve = add_equity_curve_fields(equity_curve)
    trades = order_trade_columns(trades)

    trades.to_csv(BACKTEST_TRADES_FILE, index=False)
    equity_curve.to_csv(BACKTEST_EQUITY_FILE, index=False)

    orb_summary(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=INITIAL_CAPITAL,
    )

    print(f"\nSaved backtest trades -> {BACKTEST_TRADES_FILE}")
    print(f"Saved backtest equity -> {BACKTEST_EQUITY_FILE}")


if __name__ == "__main__":
    main()