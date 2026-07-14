import sys
from datetime import datetime, timedelta

import pandas as pd

from Intraday.core.orb_config import ORB_MAX_OPEN_POSITIONS, ORB_STRATEGY_VERSION
from Intraday.scripts.auto_create_triggered_paper_trades import (
    active_positions_at_time,
    build_trade_row,
    ensure_trade_columns,
    trade_already_exists,
)


TEST_DATE = "2026-01-15"


def make_signal(ticker: str, entry_time: str) -> pd.Series:
    return pd.Series(
        {
            "ticker": ticker,
            "status": "TRIGGERED",
            "scan_date": TEST_DATE,
            "breakout_time": entry_time,
            "breakout_price": 100.0,
            "entry_trigger": 100.0,
            "stop_price": 99.0,
            "target_price": 101.0,
            "gap": 0.50,
            "opening_range_pct": 1.00,
        }
    )


def make_entry_time(minutes_after_open: int) -> pd.Timestamp:
    base = pd.Timestamp(f"{TEST_DATE} 09:30:00")
    return base + timedelta(minutes=minutes_after_open)


def fail(message: str) -> None:
    print(f"FAILED: {message}")
    sys.exit(1)


def test_capacity_blocks_after_max_positions() -> None:
    print("\nTEST 1: capacity blocks after max concurrent positions")

    if ORB_MAX_OPEN_POSITIONS < 1:
        fail("ORB_MAX_OPEN_POSITIONS must be at least 1 for this test.")

    working_trades = ensure_trade_columns(pd.DataFrame())

    created = []
    skipped = []

    candidate_count = ORB_MAX_OPEN_POSITIONS + 1

    for i in range(candidate_count):
        ticker = f"TEST{i + 1}.ST"
        entry_time = make_entry_time(i * 5)
        signal = make_signal(ticker, entry_time.strftime("%Y-%m-%d %H:%M:%S"))

        active_before = active_positions_at_time(
            working_trades,
            at_time=entry_time,
            strategy_version=ORB_STRATEGY_VERSION,
        )

        if active_before >= ORB_MAX_OPEN_POSITIONS:
            skipped.append(ticker)
            print(
                f"Skipped {ticker}: active_before={active_before}, "
                f"max={ORB_MAX_OPEN_POSITIONS}"
            )
            continue

        trade_row = build_trade_row(
            signal=signal,
            entry_time=entry_time,
            signal_rank=i + 1,
        )

        created.append(ticker)

        working_trades = ensure_trade_columns(
            pd.concat(
                [
                    working_trades,
                    pd.DataFrame([trade_row]),
                ],
                ignore_index=True,
            )
        )

        print(
            f"Created {ticker}: active_before={active_before}, "
            f"entry_time={entry_time}"
        )

    expected_created = ORB_MAX_OPEN_POSITIONS
    expected_skipped = 1

    if len(created) != expected_created:
        fail(
            f"Expected {expected_created} created trades, "
            f"but got {len(created)}."
        )

    if len(skipped) != expected_skipped:
        fail(
            f"Expected {expected_skipped} skipped trade, "
            f"but got {len(skipped)}."
        )

    print("PASSED: capacity limit works.")


def test_duplicate_detection() -> None:
    print("\nTEST 2: duplicate trade detection")

    entry_time = pd.Timestamp(f"{TEST_DATE} 09:35:00")
    ticker = "DUPLICATE.ST"

    signal = make_signal(ticker, entry_time.strftime("%Y-%m-%d %H:%M:%S"))

    trade_row = build_trade_row(
        signal=signal,
        entry_time=entry_time,
        signal_rank=1,
    )

    trades = ensure_trade_columns(pd.DataFrame([trade_row]))

    duplicate_found = trade_already_exists(
        trades=trades,
        ticker=ticker,
        entry_time=entry_time,
        strategy_version=ORB_STRATEGY_VERSION,
    )

    if not duplicate_found:
        fail("Expected duplicate trade to be detected, but it was not.")

    print("PASSED: duplicate detection works.")


def test_closed_trade_frees_capacity() -> None:
    print("\nTEST 3: closed trade before new entry frees capacity")

    rows = []

    closed_entry_time = pd.Timestamp(f"{TEST_DATE} 09:30:00")
    closed_exit_time = pd.Timestamp(f"{TEST_DATE} 09:35:00")

    closed_signal = make_signal(
        "CLOSED1.ST",
        closed_entry_time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    closed_trade = build_trade_row(
        signal=closed_signal,
        entry_time=closed_entry_time,
        signal_rank=1,
    )

    closed_trade["status"] = "CLOSED"
    closed_trade["exit_time"] = closed_exit_time.strftime("%Y-%m-%d %H:%M:%S")
    closed_trade["exit_price"] = 101.0
    closed_trade["exit_reason"] = "TARGET_HIT"
    closed_trade["pnl_pct"] = 0.01
    closed_trade["pnl_sek"] = 10.0

    rows.append(closed_trade)

    for i in range(max(ORB_MAX_OPEN_POSITIONS - 1, 0)):
        open_entry_time = pd.Timestamp(f"{TEST_DATE} 09:32:00")
        open_signal = make_signal(
            f"OPEN{i + 1}.ST",
            open_entry_time.strftime("%Y-%m-%d %H:%M:%S"),
        )

        open_trade = build_trade_row(
            signal=open_signal,
            entry_time=open_entry_time,
            signal_rank=i + 2,
        )

        open_trade["status"] = "OPEN"
        rows.append(open_trade)

    trades = ensure_trade_columns(pd.DataFrame(rows))

    new_candidate_time = pd.Timestamp(f"{TEST_DATE} 09:45:00")

    active_count = active_positions_at_time(
        trades=trades,
        at_time=new_candidate_time,
        strategy_version=ORB_STRATEGY_VERSION,
    )

    expected_active = max(ORB_MAX_OPEN_POSITIONS - 1, 0)

    print(
        f"Active at {new_candidate_time}: {active_count}, "
        f"expected={expected_active}"
    )

    if active_count != expected_active:
        fail(
            f"Expected active count {expected_active}, "
            f"but got {active_count}."
        )

    if active_count >= ORB_MAX_OPEN_POSITIONS:
        fail("Closed trade did not free capacity as expected.")

    print("PASSED: closed trades free capacity.")


def main() -> None:
    print("\n=== TEST CONCURRENT POSITION LOGIC ===")
    print(f"Strategy version: {ORB_STRATEGY_VERSION}")
    print(f"Configured max concurrent positions: {ORB_MAX_OPEN_POSITIONS}")
    print("This test is read-only and does not modify paper_trades.csv.")

    test_capacity_blocks_after_max_positions()
    test_duplicate_detection()
    test_closed_trade_frees_capacity()

    print("\nAll synthetic concurrent-position tests passed.")


if __name__ == "__main__":
    main()