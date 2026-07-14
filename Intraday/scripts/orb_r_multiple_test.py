import sqlite3
import pandas as pd


INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10
COST_PER_TRADE = 0.0005

BREAKOUT_START = pd.to_datetime("09:35").time()
BREAKOUT_END = pd.to_datetime("11:00").time()


def run_orb_test(r_multiple):
    conn = sqlite3.connect("data/intraday_prices.db")
    df = pd.read_sql("SELECT * FROM intraday_prices", conn)
    conn.close()

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.time

    opening = df[
        (df["time"] >= pd.to_datetime("09:00").time()) &
        (df["time"] <= pd.to_datetime("09:30").time())
    ]

    orb = (
        opening
        .groupby(["ticker", "date"])
        .agg(
            opening_high=("high", "max"),
            opening_low=("low", "min"),
        )
        .reset_index()
    )

    df = df.merge(orb, on=["ticker", "date"], how="left")

    equity = INITIAL_CAPITAL
    trades = []

    for (ticker, date), day in df.groupby(["ticker", "date"]):
        day = day.sort_values("datetime").copy()

        trade_window = day[
            (day["time"] >= BREAKOUT_START) &
            (day["time"] <= BREAKOUT_END)
        ]

        breakout = trade_window[
            trade_window["high"] > trade_window["opening_high"]
        ]

        if len(breakout) == 0:
            continue

        entry_row = breakout.iloc[0]
        entry_time = entry_row["datetime"]
        entry_price = entry_row["close"]

        stop_price = entry_row["opening_low"]
        risk = entry_price - stop_price

        if risk <= 0:
            continue

        target_price = entry_price + r_multiple * risk

        after_entry = day[day["datetime"] > entry_time].copy()

        exit_price = day.iloc[-1]["close"]
        exit_time = day.iloc[-1]["datetime"]
        exit_reason = "close"

        for _, row in after_entry.iterrows():
            if row["low"] <= stop_price:
                exit_price = stop_price
                exit_time = row["datetime"]
                exit_reason = "stop"
                break

            if row["high"] >= target_price:
                exit_price = target_price
                exit_time = row["datetime"]
                exit_reason = "target"
                break

        gross_return = exit_price / entry_price - 1
        net_return = gross_return - COST_PER_TRADE

        pnl = equity * POSITION_SIZE * net_return
        equity += pnl

        trades.append({
            "date": date,
            "ticker": ticker,
            "exit_reason": exit_reason,
            "gross_return": gross_return,
            "net_return": net_return,
            "pnl": pnl,
            "equity": equity,
        })

    trades = pd.DataFrame(trades)

    print("\n" + "=" * 60)
    print(f"ORB R-MULTIPLE TEST: {r_multiple}R")
    print("=" * 60)

    if len(trades) == 0:
        print("No trades found.")
        return

    total_return = equity / INITIAL_CAPITAL - 1
    win_rate = (trades["net_return"] > 0).mean()

    print(f"Trades       : {len(trades)}")
    print(f"Final equity : {equity:.2f} SEK")
    print(f"Return       : {total_return:.2%}")
    print(f"Win rate     : {win_rate:.2%}")
    print(f"Avg trade    : {trades['net_return'].mean():.4%}")

    print("\nExit reasons:")
    print(trades["exit_reason"].value_counts())


for r in [0.5, 1.0, 1.5, 2.0]:
    run_orb_test(r)