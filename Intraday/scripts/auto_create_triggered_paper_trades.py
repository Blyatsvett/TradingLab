from datetime import datetime
from pathlib import Path

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_POSITION_SIZE,
    ORB_STRATEGY_VERSION,
)
from Intraday.core.paths import ORB_SIGNALS_LATEST, PAPER_TRADES


OUTPUT_COLUMNS = [
    "trade_id",
    "date",
    "ticker",
    "side",
    "status",
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_time",
    "exit_price",
    "exit_reason",
    "pnl_pct",
    "created_at",
    "position_size_sek",
    "pnl_sek",
    "strategy_version",
    "trade_duration_minutes",
    "risk_per_share",
    "r_multiple_achieved",
    "signal_rank",
    "gap",
    "opening_range_pct",
    "breakout_time_bucket",
]


def ensure_trade_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            if column in [
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
                "gap",
                "opening_range_pct",
            ]:
                df[column] = 0.0
            else:
                df[column] = ""

    return df[OUTPUT_COLUMNS]


def read_existing_trades() -> pd.DataFrame:
    if not PAPER_TRADES.exists() or PAPER_TRADES.stat().st_size == 0:
        return ensure_trade_columns(pd.DataFrame())

    trades = pd.read_csv(PAPER_TRADES, dtype={"trade_id": str})
    return ensure_trade_columns(trades)


def read_latest_signals() -> pd.DataFrame:
    if not ORB_SIGNALS_LATEST.exists() or ORB_SIGNALS_LATEST.stat().st_size == 0:
        return pd.DataFrame()

    return pd.read_csv(ORB_SIGNALS_LATEST)


def to_datetime(value):
    converted = pd.to_datetime(value, errors="coerce")
    if pd.isna(converted):
        return pd.NaT
    return converted


def to_float(value, default: float = 0.0) -> float:
    converted = pd.to_numeric(value, errors="coerce")
    if pd.isna(converted):
        return default
    return float(converted)


def get_breakout_time_bucket(entry_time) -> str:
    entry_time = pd.to_datetime(entry_time).time()

    if entry_time <= pd.to_datetime("09:50").time():
        return "EARLY"

    if entry_time <= pd.to_datetime("10:15").time():
        return "MID"

    return "LATE"


def get_signal_entry_time(signal: pd.Series):
    breakout_time = to_datetime(signal.get("breakout_time", ""))

    if not pd.isna(breakout_time):
        return breakout_time

    scan_date = signal.get("scan_date", "")
    breakout_text = str(signal.get("breakout_time", "")).strip()

    if scan_date and breakout_text and breakout_text.lower() not in ["nat", "none", ""]:
        combined = to_datetime(f"{scan_date} {breakout_text}")
        if not pd.isna(combined):
            return combined

    return pd.NaT


def make_trade_id(entry_time, ticker: str) -> str:
    clean_ticker = (
        str(ticker)
        .replace(".", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
    )

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    entry_part = pd.to_datetime(entry_time).strftime("%Y%m%d%H%M")

    return f"PT_{entry_part}_{clean_ticker}_{timestamp}"


def trade_already_exists(
    trades: pd.DataFrame,
    ticker: str,
    entry_time,
    strategy_version: str,
) -> bool:
    if trades.empty:
        return False

    existing = trades.copy()
    existing["entry_time_dt"] = pd.to_datetime(
        existing["entry_time"],
        errors="coerce",
    )

    entry_time = pd.to_datetime(entry_time)

    duplicate = existing[
        (existing["strategy_version"].astype(str) == strategy_version)
        & (existing["ticker"].astype(str) == str(ticker))
        & (existing["entry_time_dt"] == entry_time)
    ]

    return not duplicate.empty


def reserved_exit_time(entry_time):
    entry_time = pd.to_datetime(entry_time)
    return pd.to_datetime(f"{entry_time.date()} 17:30:00")


def active_positions_at_time(
    trades: pd.DataFrame,
    at_time,
    strategy_version: str,
) -> int:
    if trades.empty:
        return 0

    at_time = pd.to_datetime(at_time)

    relevant = trades[
        trades["strategy_version"].astype(str) == strategy_version
    ].copy()

    if relevant.empty:
        return 0

    relevant["entry_time_dt"] = pd.to_datetime(
        relevant["entry_time"],
        errors="coerce",
    )

    relevant["exit_time_dt"] = pd.to_datetime(
        relevant["exit_time"],
        errors="coerce",
    )

    active_count = 0

    for _, trade in relevant.iterrows():
        entry_time = trade["entry_time_dt"]

        if pd.isna(entry_time):
            continue

        if entry_time > at_time:
            continue

        status = str(trade.get("status", "")).upper().strip()

        if status == "OPEN":
            active_count += 1
            continue

        exit_time = trade["exit_time_dt"]

        if pd.isna(exit_time):
            exit_time = reserved_exit_time(entry_time)

        if entry_time <= at_time < exit_time:
            active_count += 1

    return active_count


def build_trade_row(signal: pd.Series, entry_time, signal_rank: int) -> dict:
    ticker = str(signal["ticker"])

    entry_price = to_float(
        signal.get("breakout_price", 0.0),
        default=0.0,
    )

    if entry_price == 0.0:
        entry_price = to_float(
            signal.get("entry_trigger", 0.0),
            default=0.0,
        )

    stop_price = to_float(signal.get("stop_price", 0.0))
    target_price = to_float(signal.get("target_price", 0.0))

    risk_per_share = max(entry_price - stop_price, 0.0)

    position_size_sek = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "trade_id": make_trade_id(entry_time, ticker),
        "date": pd.to_datetime(entry_time).strftime("%Y-%m-%d"),
        "ticker": ticker,
        "side": "LONG",
        "status": "OPEN",
        "entry_time": pd.to_datetime(entry_time).strftime("%Y-%m-%d %H:%M:%S"),
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "exit_time": "",
        "exit_price": 0.0,
        "exit_reason": "",
        "pnl_pct": 0.0,
        "created_at": created_at,
        "position_size_sek": position_size_sek,
        "pnl_sek": 0.0,
        "strategy_version": ORB_STRATEGY_VERSION,
        "trade_duration_minutes": 0.0,
        "risk_per_share": risk_per_share,
        "r_multiple_achieved": 0.0,
        "signal_rank": float(signal_rank),
        "gap": to_float(signal.get("gap", 0.0)),
        "opening_range_pct": to_float(signal.get("opening_range_pct", 0.0)),
        "breakout_time_bucket": get_breakout_time_bucket(entry_time),
    }


def main() -> None:
    print("\n=== AUTO-CREATE TRIGGERED PAPER TRADES ===")

    signals = read_latest_signals()
    trades = read_existing_trades()

    if signals.empty:
        print("No latest signal file found or latest signals are empty.")
        return

    if "status" not in signals.columns:
        print("No status column found in latest signals.")
        return

    triggered = signals[
        signals["status"].astype(str).str.upper().str.strip() == "TRIGGERED"
    ].copy()

    if triggered.empty:
        print("No triggered signals found.")
        return

    triggered["entry_time"] = triggered.apply(get_signal_entry_time, axis=1)
    triggered = triggered.dropna(subset=["entry_time"])
    triggered = triggered.sort_values(["entry_time", "ticker"]).reset_index(drop=True)
    triggered["signal_rank"] = triggered.index + 1

    if triggered.empty:
        print("Triggered signals found, but none had valid breakout/entry times.")
        return

    new_rows = []
    working_trades = trades.copy()

    print(f"Strategy version: {ORB_STRATEGY_VERSION}")
    print(f"Max concurrent positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Triggered candidates: {len(triggered)}")

    for _, signal in triggered.iterrows():
        ticker = str(signal["ticker"])
        entry_time = signal["entry_time"]
        signal_rank = int(signal["signal_rank"])

        if trade_already_exists(
            working_trades,
            ticker=ticker,
            entry_time=entry_time,
            strategy_version=ORB_STRATEGY_VERSION,
        ):
            print(f"Skip duplicate: {ticker} at {entry_time}")
            continue

        active_count = active_positions_at_time(
            working_trades,
            at_time=entry_time,
            strategy_version=ORB_STRATEGY_VERSION,
        )

        if active_count >= ORB_MAX_OPEN_POSITIONS:
            print(
                "Skip capacity full: "
                f"{ticker} at {entry_time} "
                f"active={active_count}, max={ORB_MAX_OPEN_POSITIONS}"
            )
            continue

        trade_row = build_trade_row(
            signal=signal,
            entry_time=entry_time,
            signal_rank=signal_rank,
        )

        new_rows.append(trade_row)

        working_trades = pd.concat(
            [
                working_trades,
                pd.DataFrame([trade_row]),
            ],
            ignore_index=True,
        )

        print(
            "Created paper trade: "
            f"{ticker} at {trade_row['entry_time']} "
            f"rank={signal_rank} "
            f"active_before={active_count}"
        )

    if not new_rows:
        print("No new paper trades created.")
        return

    output = ensure_trade_columns(
        pd.concat(
            [
                trades,
                pd.DataFrame(new_rows),
            ],
            ignore_index=True,
        )
    )

    export_csv_for_power_bi(
        output,
        PAPER_TRADES,
        columns=OUTPUT_COLUMNS,
    )

    print(f"\nNew trades created: {len(new_rows)}")
    print(f"Saved -> {PAPER_TRADES}")


if __name__ == "__main__":
    main()