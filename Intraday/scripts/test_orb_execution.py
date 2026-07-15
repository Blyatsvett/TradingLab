import sys

import pandas as pd

from Intraday.core.orb_execution import (
    CLOSED_EOD,
    OPEN_NO_BARS,
    OPEN_NO_EXIT,
    STOP_HIT,
    TARGET_HIT,
    execute_long_orb_trade,
)


ENTRY_TIME = "2026-01-15 09:35:00"
ENTRY_PRICE = 100.0
STOP_PRICE = 99.0
TARGET_PRICE = 101.0


def make_bars(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def fail(message: str) -> None:
    print(f"FAILED: {message}")
    sys.exit(1)


def assert_close(
    actual: float,
    expected: float,
    label: str,
    tolerance: float = 1e-9,
) -> None:
    if abs(actual - expected) > tolerance:
        fail(f"{label}: expected {expected}, got {actual}")


def test_target_hit() -> None:
    print("\nTEST 1: target hit")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 101.20,
                "low": 99.80,
                "close": 100.90,
            }
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
    )

    if result.status != "CLOSED":
        fail(f"Expected CLOSED, got {result.status}")

    if result.exit_reason != TARGET_HIT:
        fail(f"Expected {TARGET_HIT}, got {result.exit_reason}")

    assert_close(result.exit_price, TARGET_PRICE, "exit_price")
    assert_close(result.pnl_pct, 0.01, "pnl_pct")
    assert_close(result.r_multiple_achieved, 1.0, "r_multiple_achieved")

    print("PASSED")


def test_stop_hit() -> None:
    print("\nTEST 2: stop hit")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 100.20,
                "low": 98.80,
                "close": 99.20,
            }
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
    )

    if result.status != "CLOSED":
        fail(f"Expected CLOSED, got {result.status}")

    if result.exit_reason != STOP_HIT:
        fail(f"Expected {STOP_HIT}, got {result.exit_reason}")

    assert_close(result.exit_price, STOP_PRICE, "exit_price")
    assert_close(result.pnl_pct, -0.01, "pnl_pct")
    assert_close(result.r_multiple_achieved, -1.0, "r_multiple_achieved")

    print("PASSED")


def test_same_bar_stop_priority() -> None:
    print("\nTEST 3: same-bar stop and target, conservative stop priority")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 101.50,
                "low": 98.50,
                "close": 100.50,
            }
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
        same_bar_priority="STOP",
    )

    if result.status != "CLOSED":
        fail(f"Expected CLOSED, got {result.status}")

    if result.exit_reason != STOP_HIT:
        fail(f"Expected {STOP_HIT}, got {result.exit_reason}")

    assert_close(result.exit_price, STOP_PRICE, "exit_price")

    print("PASSED")


def test_same_bar_target_priority() -> None:
    print("\nTEST 4: same-bar stop and target, target priority")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 101.50,
                "low": 98.50,
                "close": 100.50,
            }
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
        same_bar_priority="TARGET",
    )

    if result.status != "CLOSED":
        fail(f"Expected CLOSED, got {result.status}")

    if result.exit_reason != TARGET_HIT:
        fail(f"Expected {TARGET_HIT}, got {result.exit_reason}")

    assert_close(result.exit_price, TARGET_PRICE, "exit_price")

    print("PASSED")


def test_eod_close_uses_cutoff_bar() -> None:
    print("\nTEST 5: EOD close uses 16:30 cutoff bar")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 100.50,
                "low": 99.50,
                "close": 100.20,
            },
            {
                "datetime": "2026-01-15 16:30:00",
                "high": 100.70,
                "low": 99.40,
                "close": 100.40,
            },
            {
                "datetime": "2026-01-15 17:25:00",
                "high": 100.90,
                "low": 99.30,
                "close": 99.80,
            },
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
        close_if_no_hit=True,
        eod_exit_time="16:30",
    )

    if result.status != "CLOSED":
        fail(f"Expected CLOSED, got {result.status}")

    if result.exit_reason != CLOSED_EOD:
        fail(f"Expected {CLOSED_EOD}, got {result.exit_reason}")

    assert_close(result.exit_price, 100.40, "exit_price")
    assert_close(result.pnl_pct, 0.004, "pnl_pct")
    assert_close(result.r_multiple_achieved, 0.40, "r_multiple_achieved")

    print("PASSED")


def test_eod_close_without_cutoff_uses_last_bar() -> None:
    print("\nTEST 6: EOD close without cutoff uses final available bar")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 100.50,
                "low": 99.50,
                "close": 100.20,
            },
            {
                "datetime": "2026-01-15 16:30:00",
                "high": 100.70,
                "low": 99.40,
                "close": 100.40,
            },
            {
                "datetime": "2026-01-15 17:25:00",
                "high": 100.90,
                "low": 99.30,
                "close": 99.80,
            },
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
        close_if_no_hit=True,
        eod_exit_time=None,
    )

    if result.status != "CLOSED":
        fail(f"Expected CLOSED, got {result.status}")

    if result.exit_reason != CLOSED_EOD:
        fail(f"Expected {CLOSED_EOD}, got {result.exit_reason}")

    assert_close(result.exit_price, 99.80, "exit_price")
    assert_close(result.pnl_pct, -0.002, "pnl_pct")
    assert_close(result.r_multiple_achieved, -0.20, "r_multiple_achieved")

    print("PASSED")


def test_no_bars() -> None:
    print("\nTEST 7: no bars after entry")

    bars = make_bars([])

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
    )

    if result.status != "OPEN":
        fail(f"Expected OPEN, got {result.status}")

    if result.exit_reason != OPEN_NO_BARS:
        fail(f"Expected {OPEN_NO_BARS}, got {result.exit_reason}")

    print("PASSED")


def test_no_exit_keep_open() -> None:
    print("\nTEST 8: no stop/target and keep trade open")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 09:40:00",
                "high": 100.50,
                "low": 99.50,
                "close": 100.20,
            }
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
        close_if_no_hit=False,
    )

    if result.status != "OPEN":
        fail(f"Expected OPEN, got {result.status}")

    if result.exit_reason != OPEN_NO_EXIT:
        fail(f"Expected {OPEN_NO_EXIT}, got {result.exit_reason}")

    print("PASSED")


def test_duration_calculation() -> None:
    print("\nTEST 9: duration calculation")

    bars = make_bars(
        [
            {
                "datetime": "2026-01-15 10:05:00",
                "high": 101.20,
                "low": 99.80,
                "close": 101.00,
            }
        ]
    )

    result = execute_long_orb_trade(
        entry_time=ENTRY_TIME,
        entry_price=ENTRY_PRICE,
        stop_price=STOP_PRICE,
        target_price=TARGET_PRICE,
        bars=bars,
    )

    assert_close(result.trade_duration_minutes, 30.0, "trade_duration_minutes")

    print("PASSED")


def main() -> None:
    print("\n=== TEST ORB EXECUTION ENGINE ===")

    test_target_hit()
    test_stop_hit()
    test_same_bar_stop_priority()
    test_same_bar_target_priority()
    test_eod_close_uses_cutoff_bar()
    test_eod_close_without_cutoff_uses_last_bar()
    test_no_bars()
    test_no_exit_keep_open()
    test_duration_calculation()

    print("\nAll ORB execution tests passed.")


if __name__ == "__main__":
    main()