from __future__ import annotations

import os
import sqlite3

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import ORB_INITIAL_CAPITAL, ORB_POSITION_SIZE
from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.paths import INTRADAY_DB, PAPER_TRADES


TRADES_FILE = PAPER_TRADES
DB_FILE = INTRADAY_DB

INITIAL_CAPITAL = ORB_INITIAL_CAPITAL
POSITION_SIZE_PCT = ORB_POSITION_SIZE

EOD_EXIT_TIME = "16:30"
SAME_BAR_PRIORITY = "STOP"


TEXT_COLUMNS = [
    "exit_time",
    "exit_reason",
]

NUMERIC_COLUMNS = [
    "exit_price",
    "pnl_pct",
    "position_size_sek",
    "pnl_sek",
    "trade_duration_minutes",
    "risk_per_share",
    "r_multiple_achieved",
    "signal_rank",
]


def ensure_columns(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    required_text_columns = [
        "trade_id",
        "date",
        "ticker",
        "side",
        "status",
        "entry_time",
        "created_at",
        "strategy_version",
        "exit_time",
        "exit_reason",
    ]

    required_numeric_columns = [
        "entry_price",
        "stop_price",
        "target_price",
        "exit_price",
        "pnl_pct",
        "position_size_sek",
        "pnl_sek",
        "trade_duration_minutes",
        "risk_per_share",
        "r_multiple_achieved",
        "signal_rank",
    ]

    for col in required_text_columns:
        if col not in trades.columns:
            trades[col] = ""

    for col in required_numeric_columns:
        if col not in trades.columns:
            trades[col] = 0

    for col in required_numeric_columns:
        trades[col] = pd.to_numeric(trades[col], errors="coerce").fillna(0)

    for col in required_text_columns:
        trades[col] = trades[col].fillna("").astype("object")

    trades["status"] = trades["status"].astype(str).str.upper().str.strip()

    return trades


def load_prices_from_db() -> pd.DataFrame:
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"Missing intraday database: {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)

    try:
        prices = pd.read_sql("SELECT * FROM intraday_prices", conn)
    finally:
        conn.close()

    if prices.empty:
        raise ValueError("intraday_prices table is empty.")

    required_columns = [
        "ticker",
        "datetime",
        "high",
        "low",
        "close",
    ]

    for column in required_columns:
        if column not in prices.columns:
            raise ValueError(f"intraday_prices missing required column: {column}")

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


def get_trade_day_bars(
    prices: pd.DataFrame,
    ticker: str,
    entry_time: pd.Timestamp,
) -> pd.DataFrame:
    ticker_prices = prices[prices["ticker"].astype(str) == ticker].copy()

    if ticker_prices.empty:
        return pd.DataFrame()

    trade_date = entry_time.date()

    day_bars = ticker_prices[
        ticker_prices["datetime"].dt.date == trade_date
    ].copy()

    day_bars = day_bars.sort_values("datetime").reset_index(drop=True)

    return day_bars


def should_close_no_hit_at_eod(day_bars: pd.DataFrame) -> bool:
    """
    Return True only once the latest available bar for the trade date is at
    or after the configured EOD paper exit time.

    Before that, open trades should remain OPEN unless stop or target is hit.
    """

    if day_bars.empty:
        return False

    latest_bar_time = day_bars["datetime"].max()

    if pd.isna(latest_bar_time):
        return False

    latest_bar_clock = latest_bar_time.strftime("%H:%M")

    return latest_bar_clock >= EOD_EXIT_TIME


def update_open_trade(
    trades: pd.DataFrame,
    idx: int,
    trade: pd.Series,
    prices: pd.DataFrame,
) -> bool:
    ticker = str(trade["ticker"])
    entry_time = pd.to_datetime(trade["entry_time"], errors="coerce")

    if pd.isna(entry_time):
        print(f"Skipping trade with invalid entry_time: index={idx}, ticker={ticker}")
        return False

    day_bars = get_trade_day_bars(
        prices=prices,
        ticker=ticker,
        entry_time=entry_time,
    )

    if day_bars.empty:
        print(f"No prices found for open trade: ticker={ticker}, entry_time={entry_time}")
        return False

    entry_price = float(trade["entry_price"])
    stop_price = float(trade["stop_price"])
    target_price = float(trade["target_price"])

    close_if_no_hit = should_close_no_hit_at_eod(day_bars)

    latest_bar_time = day_bars["datetime"].max()
    latest_bar_clock = latest_bar_time.strftime("%H:%M")

    result = execute_long_orb_trade(
        entry_time=entry_time,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        bars=day_bars,
        timestamp_col="datetime",
        close_if_no_hit=close_if_no_hit,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
    )

    if result.status != "CLOSED":
        print(
            "Trade remains open: "
            f"ticker={ticker}, "
            f"entry_time={entry_time}, "
            f"latest_bar={latest_bar_time}, "
            f"latest_bar_clock={latest_bar_clock}, "
            f"reason={result.exit_reason}"
        )
        return False

    position_size_sek = INITIAL_CAPITAL * POSITION_SIZE_PCT
    pnl_sek = position_size_sek * result.pnl_pct

    trades.loc[idx, "status"] = "CLOSED"
    trades.loc[idx, "exit_time"] = result.exit_time
    trades.loc[idx, "exit_price"] = result.exit_price
    trades.loc[idx, "exit_reason"] = result.exit_reason
    trades.loc[idx, "pnl_pct"] = result.pnl_pct
    trades.loc[idx, "position_size_sek"] = position_size_sek
    trades.loc[idx, "pnl_sek"] = pnl_sek
    trades.loc[idx, "trade_duration_minutes"] = result.trade_duration_minutes
    trades.loc[idx, "risk_per_share"] = result.risk_per_share
    trades.loc[idx, "r_multiple_achieved"] = result.r_multiple_achieved

    print(
        "Closed trade: "
        f"ticker={ticker}, "
        f"entry_time={entry_time}, "
        f"exit_time={result.exit_time}, "
        f"exit_reason={result.exit_reason}, "
        f"pnl_sek={pnl_sek:.2f}"
    )

    return True


def main() -> None:
    print("\n=== UPDATE PAPER TRADES ===")
    print("Using shared ORB execution engine.")
    print(f"EOD exit time: {EOD_EXIT_TIME}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(
        "Intraday no-hit rule: keep trades OPEN before EOD unless "
        "STOP_HIT or TARGET_HIT occurs."
    )

    if not os.path.exists(TRADES_FILE):
        print(f"Missing trades file: {TRADES_FILE}")
        return

    trades = pd.read_csv(TRADES_FILE, dtype={"trade_id": str})

    if trades.empty:
        print("No paper trades found.")
        return

    trades = ensure_columns(trades)
    prices = load_prices_from_db()

    updated = 0
    open_trades = 0

    for idx, trade in trades.iterrows():
        status = str(trade["status"]).upper().strip()

        if status != "OPEN":
            continue

        open_trades += 1

        was_updated = update_open_trade(
            trades=trades,
            idx=idx,
            trade=trade,
            prices=prices,
        )

        if was_updated:
            updated += 1

    export_csv_for_power_bi(trades, TRADES_FILE)

    print("\n=== PAPER TRADES UPDATED ===")
    print(f"Open trades checked: {open_trades}")
    print(f"Updated trades: {updated}")
    print(trades.to_string(index=False))
    print(f"\nSaved -> {TRADES_FILE}")


if __name__ == "__main__":
    main()