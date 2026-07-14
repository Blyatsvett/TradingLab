import sys
import os
import pandas as pd
from Intraday.core.paths import ORB_SIGNALS_LATEST, PAPER_TRADES


SIGNALS_FILE = ORB_SIGNALS_LATEST
TRADES_FILE = PAPER_TRADES
INITIAL_STATUS = "OPEN"


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("python -m Intraday.scripts.create_paper_trade TICKER")
        return

    ticker = sys.argv[1].upper()

    if not os.path.exists(SIGNALS_FILE):
        print(f"Missing signals file: {SIGNALS_FILE}")
        return

    signals = pd.read_csv(SIGNALS_FILE)

    signal = signals[signals["ticker"] == ticker]

    if len(signal) == 0:
        print(f"No signal found for {ticker}")
        return

    signal = signal.iloc[0]

    if signal["status"] != "TRIGGERED":
        print(f"{ticker} is not triggered. Current status: {signal['status']}")
        return

    trade = {
        "trade_id": pd.Timestamp.now().strftime("%Y%m%d%H%M%S"),
        "date": str(signal["last_bar"])[:10],
        "ticker": signal["ticker"],
        "side": "LONG",
        "status": INITIAL_STATUS,
        "entry_time": signal["breakout_time"],
        "entry_price": signal["breakout_price"],
        "stop_price": signal["stop_price"],
        "target_price": signal["target_price"],
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "pnl_pct": None,
        "created_at": pd.Timestamp.now(),
    }

    trade_df = pd.DataFrame([trade])

    os.makedirs("data", exist_ok=True)

    if os.path.exists(TRADES_FILE):
        old = pd.read_csv(TRADES_FILE)

        duplicate = old[
            (old["ticker"] == trade["ticker"]) &
            (old["date"] == trade["date"]) &
            (old["side"] == trade["side"])
        ]

        if len(duplicate) > 0:
            print(f"Paper trade already exists for {ticker} on {trade['date']}")
            return

        combined = pd.concat([old, trade_df], ignore_index=True)
        combined.to_csv(TRADES_FILE, index=False)
    else:
        trade_df.to_csv(TRADES_FILE, index=False)

    print("\n=== PAPER TRADE CREATED ===")
    print(trade_df.to_string(index=False))
    print(f"\nSaved -> {TRADES_FILE}")


if __name__ == "__main__":
    main()