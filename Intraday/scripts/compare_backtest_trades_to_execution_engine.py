import sys

import pandas as pd

from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.orb_strategy import load_intraday_prices
from Intraday.core.paths import DATA_DIR


BACKTEST_TRADES = DATA_DIR / "orb_backtest_trades.csv"

PRICE_TOLERANCE = 0.01
RETURN_TOLERANCE = 0.0001


EXIT_REASON_MAP = {
    "stop": "STOP_HIT",
    "target": "TARGET_HIT",
    "close": "CLOSED_EOD",
}


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {column.lower(): column for column in df.columns}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    return None


def normalise_intraday_prices(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()

    ticker_col = find_column(prices, ["ticker", "symbol"])
    high_col = find_column(prices, ["high"])
    low_col = find_column(prices, ["low"])
    close_col = find_column(prices, ["close"])
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

    if ticker_col is None:
        raise ValueError("Could not find ticker column in intraday prices.")

    if high_col is None or low_col is None or close_col is None:
        raise ValueError("Could not find high/low/close columns in intraday prices.")

    if timestamp_col is None:
        raise ValueError("Could not find datetime/timestamp column in intraday prices.")

    output = pd.DataFrame(
        {
            "ticker": prices[ticker_col].astype(str),
            "datetime": pd.to_datetime(prices[timestamp_col], errors="coerce"),
            "high": pd.to_numeric(prices[high_col], errors="coerce"),
            "low": pd.to_numeric(prices[low_col], errors="coerce"),
            "close": pd.to_numeric(prices[close_col], errors="coerce"),
        }
    )

    output = output.dropna(subset=["ticker", "datetime", "high", "low", "close"])
    output = output.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    return output


def load_backtest_trades() -> pd.DataFrame:
    if not BACKTEST_TRADES.exists() or BACKTEST_TRADES.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty backtest trades file: {BACKTEST_TRADES}")

    trades = pd.read_csv(BACKTEST_TRADES)

    required_columns = [
        "date",
        "ticker",
        "entry_time",
        "exit_time",
        "exit_reason",
        "entry_price",
        "stop_price",
        "target_price",
        "exit_price",
        "gross_return",
    ]

    for column in required_columns:
        if column not in trades.columns:
            raise ValueError(f"orb_backtest_trades missing required column: {column}")

    return trades


def compare_trade(
    trade_number: int,
    trade: pd.Series,
    prices: pd.DataFrame,
) -> dict:
    ticker = str(trade["ticker"])
    entry_time = pd.to_datetime(trade["entry_time"], errors="coerce")

    if pd.isna(entry_time):
        return {
            "trade_number": trade_number,
            "ticker": ticker,
            "match": False,
            "issue": "Invalid entry_time",
        }

    ticker_prices = prices[prices["ticker"] == ticker].copy()

    if ticker_prices.empty:
        return {
            "trade_number": trade_number,
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
            "trade_number": trade_number,
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
        eod_exit_time=None,
    )

    expected_exit_reason_raw = str(trade["exit_reason"]).lower().strip()
    expected_exit_reason = EXIT_REASON_MAP.get(
        expected_exit_reason_raw,
        expected_exit_reason_raw,
    )

    actual_exit_reason = result.exit_reason

    expected_exit_price = pd.to_numeric(trade["exit_price"], errors="coerce")
    expected_gross_return = pd.to_numeric(trade["gross_return"], errors="coerce")

    exit_reason_match = expected_exit_reason == actual_exit_reason

    exit_price_match = (
        pd.notna(expected_exit_price)
        and abs(float(expected_exit_price) - result.exit_price) <= PRICE_TOLERANCE
    )

    gross_return_match = (
        pd.notna(expected_gross_return)
        and abs(float(expected_gross_return) - result.pnl_pct) <= RETURN_TOLERANCE
    )

    all_match = exit_reason_match and exit_price_match and gross_return_match

    issue_parts = []

    if not exit_reason_match:
        issue_parts.append(
            f"exit_reason expected={expected_exit_reason}, actual={actual_exit_reason}"
        )

    if not exit_price_match:
        issue_parts.append(
            f"exit_price expected={float(expected_exit_price):.4f}, actual={result.exit_price:.4f}"
        )

    if not gross_return_match:
        issue_parts.append(
            f"gross_return expected={float(expected_gross_return):.6f}, actual={result.pnl_pct:.6f}"
        )

    return {
        "trade_number": trade_number,
        "date": str(trade["date"]),
        "ticker": ticker,
        "entry_time": str(entry_time),
        "expected_exit_reason": expected_exit_reason,
        "actual_exit_reason": actual_exit_reason,
        "expected_exit_price": float(expected_exit_price),
        "actual_exit_price": result.exit_price,
        "expected_gross_return": float(expected_gross_return),
        "actual_gross_return": result.pnl_pct,
        "match": all_match,
        "issue": " | ".join(issue_parts),
    }


def main() -> None:
    print("\n=== COMPARE BACKTEST TRADES TO SHARED EXECUTION ENGINE ===")
    print("This is read-only. It does not modify backtest CSVs.")
    print("Backtest comparison uses eod_exit_time=None to match current last-bar close behavior.")

    trades = load_backtest_trades()

    if trades.empty:
        print("No backtest trades to compare.")
        return

    print(f"Backtest trades to compare: {len(trades)}")

    raw_prices = load_intraday_prices()
    prices = normalise_intraday_prices(raw_prices)

    results = []

    for i, (_, trade) in enumerate(trades.iterrows(), start=1):
        trade_number = int(trade["trade_number"]) if "trade_number" in trades.columns else i

        result = compare_trade(
            trade_number=trade_number,
            trade=trade,
            prices=prices,
        )

        results.append(result)

    result_df = pd.DataFrame(results)

    matches = int(result_df["match"].sum())
    mismatches = len(result_df) - matches

    print(f"\nMatches: {matches}")
    print(f"Mismatches: {mismatches}")

    display_columns = [
        "trade_number",
        "date",
        "ticker",
        "expected_exit_reason",
        "actual_exit_reason",
        "expected_exit_price",
        "actual_exit_price",
        "expected_gross_return",
        "actual_gross_return",
        "match",
        "issue",
    ]

    print("\n=== FIRST 30 COMPARISON ROWS ===")
    print(result_df[display_columns].head(30).to_string(index=False))

    if mismatches > 0:
        print("\n=== MISMATCHES ===")
        print(
            result_df.loc[
                ~result_df["match"],
                display_columns,
            ].to_string(index=False)
        )
        print("\nComparison found mismatches. Review before refactoring run_orb_backtest.py.")
        sys.exit(1)

    print("\nAll backtest trades match the shared execution engine.")


if __name__ == "__main__":
    main()