import sqlite3
import pandas as pd


INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10
COST_PER_TRADE = 0.0005

BREAKOUT_START = pd.to_datetime("09:35").time()
BREAKOUT_END = pd.to_datetime("11:00").time()


conn = sqlite3.connect("data/intraday_prices.db")
df = pd.read_sql("SELECT * FROM intraday_prices", conn)
conn.close()

df["datetime"] = pd.to_datetime(df["datetime"])
df["date"] = df["datetime"].dt.date
df["time"] = df["datetime"].dt.time

opening = df[
    (df["time"] >= pd.to_datetime("09:00").time()) &
    (df["time"] <= pd.to_datetime("09:30").time())
].copy()

orb = (
    opening
    .groupby(["ticker", "date"])
    .agg(
        opening_high=("high", "max"),
        opening_low=("low", "min"),
        opening_volume=("volume", "sum"),
        opening_avg_volume=("volume", "mean"),
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
        (trade_window["high"] > trade_window["opening_high"]) &
        (trade_window["volume"] > trade_window["opening_avg_volume"])
    ]

    if len(breakout) == 0:
        continue

    entry_row = breakout.iloc[0]
    exit_row = day.iloc[-1]

    entry_price = entry_row["close"]
    exit_price = exit_row["close"]

    gross_return = exit_price / entry_price - 1
    net_return = gross_return - COST_PER_TRADE

    pnl = equity * POSITION_SIZE * net_return
    equity += pnl

    trades.append({
        "date": date,
        "ticker": ticker,
        "entry_time": entry_row["datetime"],
        "exit_time": exit_row["datetime"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "breakout_volume": entry_row["volume"],
        "opening_avg_volume": entry_row["opening_avg_volume"],
        "gross_return": gross_return,
        "net_return": net_return,
        "pnl": pnl,
        "equity": equity,
    })


trades = pd.DataFrame(trades)

print("\n=== ORB BACKTEST V3: TIME + VOLUME FILTER ===")

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