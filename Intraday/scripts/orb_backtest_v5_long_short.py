import sqlite3
import pandas as pd


INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10
COST_PER_TRADE = 0.0005

BREAKOUT_START = pd.to_datetime("09:35").time()
BREAKOUT_END = pd.to_datetime("11:00").time()
R_MULTIPLE = 1.0


def load_data():
    conn = sqlite3.connect("data/intraday_prices.db")
    df = pd.read_sql("SELECT * FROM intraday_prices", conn)
    conn.close()

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.time

    return df


df = load_data()

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

    long_breakouts = trade_window[
        trade_window["high"] > trade_window["opening_high"]
    ]

    short_breakouts = trade_window[
        trade_window["low"] < trade_window["opening_low"]
    ]

    long_entry = long_breakouts.iloc[0] if len(long_breakouts) > 0 else None
    short_entry = short_breakouts.iloc[0] if len(short_breakouts) > 0 else None

    if long_entry is None and short_entry is None:
        continue

    if long_entry is not None and short_entry is not None:
        if long_entry["datetime"] <= short_entry["datetime"]:
            entry_row = long_entry
            direction = "long"
        else:
            entry_row = short_entry
            direction = "short"
    elif long_entry is not None:
        entry_row = long_entry
        direction = "long"
    else:
        entry_row = short_entry
        direction = "short"

    entry_time = entry_row["datetime"]
    entry_price = entry_row["close"]

    if direction == "long":
        stop_price = entry_row["opening_low"]
        risk = entry_price - stop_price

        if risk <= 0:
            continue

        target_price = entry_price + R_MULTIPLE * risk

    else:
        stop_price = entry_row["opening_high"]
        risk = stop_price - entry_price

        if risk <= 0:
            continue

        target_price = entry_price - R_MULTIPLE * risk

    after_entry = day[day["datetime"] > entry_time].copy()

    exit_price = day.iloc[-1]["close"]
    exit_time = day.iloc[-1]["datetime"]
    exit_reason = "close"

    for _, row in after_entry.iterrows():

        if direction == "long":
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

        else:
            if row["high"] >= stop_price:
                exit_price = stop_price
                exit_time = row["datetime"]
                exit_reason = "stop"
                break

            if row["low"] <= target_price:
                exit_price = target_price
                exit_time = row["datetime"]
                exit_reason = "target"
                break

    if direction == "long":
        gross_return = exit_price / entry_price - 1
    else:
        gross_return = entry_price / exit_price - 1

    net_return = gross_return - COST_PER_TRADE

    pnl = equity * POSITION_SIZE * net_return
    equity += pnl

    trades.append({
        "date": date,
        "ticker": ticker,
        "direction": direction,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": exit_reason,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "exit_price": exit_price,
        "gross_return": gross_return,
        "net_return": net_return,
        "pnl": pnl,
        "equity": equity,
    })


trades = pd.DataFrame(trades)

print("\n=== ORB BACKTEST V5: LONG + SHORT ===")

if len(trades) == 0:
    print("No trades found.")
else:
    print(trades.tail(20))

    total_return = equity / INITIAL_CAPITAL - 1
    win_rate = (trades["net_return"] > 0).mean()

    print("\n=== SUMMARY ===")
    print(f"Trades       : {len(trades)}")
    print(f"Final equity : {equity:.2f} SEK")
    print(f"Return       : {total_return:.2%}")
    print(f"Win rate     : {win_rate:.2%}")
    print(f"Avg trade    : {trades['net_return'].mean():.4%}")

    print("\n=== BY DIRECTION ===")
    print(
        trades.groupby("direction")["net_return"]
        .agg(["count", "mean"])
    )

    print("\n=== EXIT REASONS ===")
    print(trades["exit_reason"].value_counts())