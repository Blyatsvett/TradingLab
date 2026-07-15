import sys

import pandas as pd

from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.orb_strategy import load_intraday_prices
from Intraday.core.paths import PAPER_TRADES


PRICE_TOLERANCE = 0.01
PNL_TOLERANCE = 0.0001


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {column.lower(): column for column in df.columns}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    return None


def normalise_intraday_prices(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()

    ticker_col = find_column(prices, ["ticker", "symbol"])
    if ticker_col is None:
        raise ValueError("Could not find ticker column in intraday prices.")

    high_col = find_column(prices, ["high"])
    low_col = find_column(prices, ["low"])
    close_col = find_column(prices, ["close"])

    if high_col is None or low_col is None or close_col is None:
        raise ValueError("Could not find high/low/close columns in intraday prices.")

    timestamp_col = find_column(
        prices,
        [
            "datetime",
            "timestamp",
            "date_time",
            "Datetime",
            "Timestamp",
            "time",
            "Time",
        ],
    )

    if timestamp_col is not None:
        prices["bar_time"] = pd.to_datetime(prices[timestamp_col], errors="coerce")
    else:
        date_col = find_column(prices, ["date"])
        time_col = find_column(prices, ["bar_time", "clock_time", "time"])

        if date_col is None or time_col is None:
            raise ValueError(
                "Could not find timestamp column, or date + time columns, "
                "in intraday prices."
            )

        prices["bar_time"] = pd.to_datetime(
            prices[date_col].astype(str) + " " + prices[time_col].astype(str),
            errors="coerce",
        )

    output = pd.DataFrame(
        {
            "ticker": prices[ticker_col].astype(str),
            "datetime": prices["bar_time"],
            "high": pd.to_numeric(prices[high_col], errors="coerce"),
            "low": pd.to_numeric(prices[low_col], errors="coerce"),
            "close": pd.to_numeric(prices[close_col], errors="coerce"),
        }
    )

    output = output.dropna(subset=["datetime", "high", "low", "close"])
    output = output.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    return output


def load_trades() -> pd.DataFrame:
    if not PAPER_TRADES.exists() or PAPER_TRADES.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty paper trades file: {PAPER_TRADES}")

    trades = pd.read_csv(PAPER_TRADES, dtype={"trade_id": str})

    required_columns = [
        "trade_id",
        "ticker",
        "status",
        "entry_time",
        "entry_price",
        "stop_price",
        "target_price",
        "exit_time",
        "exit_price",
        "exit_reason",
        "pnl_pct",
    ]

    for column in required_columns:
        if column not in trades.columns:
            raise ValueError(f"paper_trades missing required column: {column}")

    return trades


def compare_trade(
    trade: pd.Series,
    prices: pd.DataFrame,
) -> dict:
    trade_id = str(trade["trade_id"])
    ticker = str(trade["ticker"])
    entry_time = pd.to_datetime(trade["entry_time"], errors="coerce")

    if pd.isna(entry_time):
        return {
            "trade_id": trade_id,
            "ticker": ticker,
            "match": False,
            "issue": "Invalid entry_time",
        }

    ticker_prices = prices[prices["ticker"] == ticker].copy()

    if ticker_prices.empty:
        return {
            "trade_id": trade_id,
            "ticker": ticker,
            "match": False,
            "issue": "No prices found for ticker",
        }

    trade_date = entry_time.date()

    bars = ticker_prices[
        ticker_prices["datetime"].dt.date == trade_date
    ].copy()

    if bars.empty:
        return {
            "trade_id": trade_id,
            "ticker": ticker,
            "match": False,
            "issue": "No bars found for trade date",
        }

    result = execute_long_orb_trade(
        entry_time=entry_time,
        entry_price=float(trade["entry_price"]),
        stop_price=float(trade["stop_price"]),
        target_price=float(trade["target_price"]),
        bars=bars,
        timestamp_col="datetime",
        close_if_no_hit=True,
        same_bar_priority="STOP",
        eod_exit_time="16:30",
    )

    expected_exit_reason = str(trade["exit_reason"])
    actual_exit_reason = result.exit_reason

    expected_exit_price = pd.to_numeric(trade["exit_price"], errors="coerce")
    expected_pnl_pct = pd.to_numeric(trade["pnl_pct"], errors="coerce")

    exit_reason_match = expected_exit_reason == actual_exit_reason

    exit_price_match = (
        pd.notna(expected_exit_price)
        and abs(float(expected_exit_price) - result.exit_price) <= PRICE_TOLERANCE
    )

    pnl_match = (
        pd.notna(expected_pnl_pct)
        and abs(float(expected_pnl_pct) - result.pnl_pct) <= PNL_TOLERANCE
    )

    all_match = exit_reason_match and exit_price_match and pnl_match

    issue_parts = []

    if not exit_reason_match:
        issue_parts.append(
            f"exit_reason expected={expected_exit_reason}, actual={actual_exit_reason}"
        )

    if not exit_price_match:
        issue_parts.append(
            f"exit_price expected={float(expected_exit_price):.4f}, actual={result.exit_price:.4f}"
        )

    if not pnl_match:
        issue_parts.append(
            f"pnl_pct expected={float(expected_pnl_pct):.6f}, actual={result.pnl_pct:.6f}"
        )

    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "entry_time": str(entry_time),
        "expected_exit_reason": expected_exit_reason,
        "actual_exit_reason": actual_exit_reason,
        "expected_exit_price": float(expected_exit_price),
        "actual_exit_price": result.exit_price,
        "expected_pnl_pct": float(expected_pnl_pct),
        "actual_pnl_pct": result.pnl_pct,
        "match": all_match,
        "issue": " | ".join(issue_parts),
    }


def main() -> None:
    print("\n=== COMPARE PAPER TRADES TO SHARED EXECUTION ENGINE ===")
    print("This is read-only. It does not modify paper_trades.csv.")

    trades = load_trades()

    closed = trades[
        trades["status"].astype(str).str.upper().str.strip() == "CLOSED"
    ].copy()

    if closed.empty:
        print("No closed paper trades to compare.")
        return

    print(f"Closed paper trades to compare: {len(closed)}")

    raw_prices = load_intraday_prices()
    prices = normalise_intraday_prices(raw_prices)

    results = []

    for _, trade in closed.iterrows():
        result = compare_trade(trade=trade, prices=prices)
        results.append(result)

    result_df = pd.DataFrame(results)

    matches = int(result_df["match"].sum())
    mismatches = len(result_df) - matches

    print(f"\nMatches: {matches}")
    print(f"Mismatches: {mismatches}")

    display_columns = [
        "trade_id",
        "ticker",
        "expected_exit_reason",
        "actual_exit_reason",
        "expected_exit_price",
        "actual_exit_price",
        "expected_pnl_pct",
        "actual_pnl_pct",
        "match",
        "issue",
    ]

    print("\n=== COMPARISON DETAIL ===")
    print(result_df[display_columns].to_string(index=False))

    if mismatches > 0:
        print("\nComparison found mismatches. Review before refactoring update_paper_trades.py.")
        sys.exit(1)

    print("\nAll closed paper trades match the shared execution engine.")


if __name__ == "__main__":
    main()