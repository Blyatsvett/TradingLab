import os
import pandas as pd
from Intraday.core.export_utils import export_csv_for_power_bi

from Intraday.core.paths import PAPER_TRADES, ORB_SIGNAL_HISTORY


def get_breakout_time_bucket(entry_time):
    entry_time = pd.to_datetime(entry_time, errors="coerce")

    if pd.isna(entry_time):
        return "UNKNOWN"

    t = entry_time.time()

    if t <= pd.to_datetime("09:50").time():
        return "EARLY"

    if t <= pd.to_datetime("10:15").time():
        return "MID"

    return "LATE"


def main():
    if not os.path.exists(PAPER_TRADES):
        print(f"Missing paper trades file: {PAPER_TRADES}")
        return

    if not os.path.exists(ORB_SIGNAL_HISTORY):
        print(f"Missing signal history file: {ORB_SIGNAL_HISTORY}")
        return

    trades = pd.read_csv(PAPER_TRADES)
    signals = pd.read_csv(ORB_SIGNAL_HISTORY)

    if len(trades) == 0:
        print("No paper trades found.")
        return

    if len(signals) == 0:
        print("No ORB signal history found.")
        return

    if "gap" not in trades.columns:
        trades["gap"] = 0.0

    if "opening_range_pct" not in trades.columns:
        trades["opening_range_pct"] = 0.0

    if "breakout_time_bucket" not in trades.columns:
        trades["breakout_time_bucket"] = "UNKNOWN"

    trades["gap"] = pd.to_numeric(trades["gap"], errors="coerce").fillna(0).astype(float)
    trades["opening_range_pct"] = pd.to_numeric(
        trades["opening_range_pct"],
        errors="coerce",
    ).fillna(0).astype(float)

    trades["breakout_time_bucket"] = trades["breakout_time_bucket"].astype("object")

    trades["entry_time_dt"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    signals["breakout_time_dt"] = pd.to_datetime(signals["breakout_time"], errors="coerce")

    updated = 0

    for idx, trade in trades.iterrows():
        ticker = trade["ticker"]
        entry_time = trade["entry_time_dt"]

        if pd.isna(entry_time):
            continue

        match = signals[
            (signals["ticker"].astype(str) == str(ticker))
            & (signals["breakout_time_dt"] == entry_time)
        ]

        if len(match) == 0:
            # No matching signal found, but still create bucket from entry_time
            trades.loc[idx, "breakout_time_bucket"] = get_breakout_time_bucket(entry_time)
            continue

        signal = match.iloc[0]

        trades.loc[idx, "gap"] = signal.get("gap", 0)
        trades.loc[idx, "opening_range_pct"] = signal.get("opening_range_pct", 0)
        trades.loc[idx, "breakout_time_bucket"] = get_breakout_time_bucket(entry_time)

        updated += 1

    trades = trades.drop(columns=["entry_time_dt"])

    trades["gap"] = pd.to_numeric(trades["gap"], errors="coerce").fillna(0)
    trades["opening_range_pct"] = pd.to_numeric(
        trades["opening_range_pct"],
        errors="coerce",
    ).fillna(0)

    export_csv_for_power_bi(trades, PAPER_TRADES)

    print("\n=== PAPER TRADE SIGNAL METADATA BACKFILLED ===")
    print(f"Updated rows with matching signals: {updated}")
    print(
        trades[
            [
                "date",
                "ticker",
                "entry_time",
                "gap",
                "opening_range_pct",
                "breakout_time_bucket",
            ]
        ].to_string(index=False)
    )

    print(f"\nSaved -> {PAPER_TRADES}")


if __name__ == "__main__":
    main()