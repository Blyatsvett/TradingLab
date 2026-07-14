import os
import sqlite3
import pandas as pd

from Intraday.core.paths import PAPER_TRADES, INTRADAY_DB
from Intraday.core.export_utils import export_csv_for_power_bi


TRADES_FILE = PAPER_TRADES
DB_FILE = INTRADAY_DB

INITIAL_CAPITAL = 10000
POSITION_SIZE_PCT = 0.10


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


def ensure_columns(trades):
    for col in TEXT_COLUMNS:
        if col not in trades.columns:
            trades[col] = None

    for col in NUMERIC_COLUMNS:
        if col not in trades.columns:
            trades[col] = 0

    for col in NUMERIC_COLUMNS:
        trades[col] = pd.to_numeric(trades[col], errors="coerce").fillna(0)

    trades["exit_time"] = trades["exit_time"].astype("object")
    trades["exit_reason"] = trades["exit_reason"].astype("object")

    return trades


def calculate_trade_quality(entry_time, exit_time, entry_price, stop_price, exit_price):
    entry_time_dt = pd.to_datetime(entry_time)
    exit_time_dt = pd.to_datetime(exit_time)

    trade_duration_minutes = (
        exit_time_dt - entry_time_dt
    ).total_seconds() / 60

    risk_per_share = entry_price - stop_price

    if risk_per_share > 0:
        r_multiple_achieved = (exit_price - entry_price) / risk_per_share
    else:
        r_multiple_achieved = 0

    return trade_duration_minutes, risk_per_share, r_multiple_achieved


def main():
    if not os.path.exists(TRADES_FILE):
        print(f"Missing trades file: {TRADES_FILE}")
        return

    trades = pd.read_csv(TRADES_FILE)

    if len(trades) == 0:
        print("No paper trades found.")
        return

    trades = ensure_columns(trades)

    conn = sqlite3.connect(DB_FILE)
    prices = pd.read_sql("SELECT * FROM intraday_prices", conn)
    conn.close()

    prices["datetime"] = pd.to_datetime(prices["datetime"])

    updated = 0

    for idx, trade in trades.iterrows():
        if trade["status"] != "OPEN":
            continue

        ticker = trade["ticker"]
        entry_time = pd.to_datetime(trade["entry_time"])

        ticker_prices = prices[
            (prices["ticker"] == ticker)
            & (prices["datetime"] > entry_time)
        ].sort_values("datetime")

        if len(ticker_prices) == 0:
            continue

        stop_price = float(trade["stop_price"])
        target_price = float(trade["target_price"])
        entry_price = float(trade["entry_price"])

        exit_time = None
        exit_price = None
        exit_reason = None

        for _, row in ticker_prices.iterrows():
            if row["low"] <= stop_price:
                exit_time = row["datetime"]
                exit_price = stop_price
                exit_reason = "STOP_HIT"
                break

            if row["high"] >= target_price:
                exit_time = row["datetime"]
                exit_price = target_price
                exit_reason = "TARGET_HIT"
                break

        if exit_reason is None:
            last_row = ticker_prices.iloc[-1]
            exit_time = last_row["datetime"]
            exit_price = float(last_row["close"])
            exit_reason = "CLOSED_EOD"

        pnl_pct = exit_price / entry_price - 1
        position_size_sek = INITIAL_CAPITAL * POSITION_SIZE_PCT
        pnl_sek = position_size_sek * pnl_pct

        (
            trade_duration_minutes,
            risk_per_share,
            r_multiple_achieved,
        ) = calculate_trade_quality(
            entry_time=trade["entry_time"],
            exit_time=exit_time,
            entry_price=entry_price,
            stop_price=stop_price,
            exit_price=exit_price,
        )

        trades.loc[idx, "status"] = "CLOSED"
        trades.loc[idx, "exit_time"] = str(exit_time)
        trades.loc[idx, "exit_price"] = exit_price
        trades.loc[idx, "exit_reason"] = exit_reason
        trades.loc[idx, "pnl_pct"] = pnl_pct
        trades.loc[idx, "position_size_sek"] = position_size_sek
        trades.loc[idx, "pnl_sek"] = pnl_sek
        trades.loc[idx, "trade_duration_minutes"] = trade_duration_minutes
        trades.loc[idx, "risk_per_share"] = risk_per_share
        trades.loc[idx, "r_multiple_achieved"] = r_multiple_achieved

        updated += 1

    export_csv_for_power_bi(trades, TRADES_FILE)

    print("\n=== PAPER TRADES UPDATED ===")
    print(f"Updated trades: {updated}")
    print(trades.to_string(index=False))
    print(f"\nSaved -> {TRADES_FILE}")


if __name__ == "__main__":
    main()