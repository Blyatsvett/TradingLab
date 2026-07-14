import sqlite3
import pandas as pd


INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10
COST_PER_TRADE = 0.0005

BREAKOUT_START = pd.to_datetime("09:35").time()
BREAKOUT_END = pd.to_datetime("11:00").time()
R_MULTIPLE = 1.0
MAX_OPENING_RANGE = 0.02
MIN_GAP = 0.0


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
    opening.groupby(["ticker", "date"])
    .agg(
        opening_high=("high", "max"),
        opening_low=("low", "min"),
        day_open=("open", "first"),
    )
    .reset_index()
)

orb["opening_range_pct"] = orb["opening_high"] / orb["opening_low"] - 1
orb["prev_open"] = orb.groupby("ticker")["day_open"].shift(1)
orb["gap"] = orb["day_open"] / orb["prev_open"] - 1

df = df.merge(
    orb[
        [
            "ticker",
            "date",
            "opening_high",
            "opening_low",
            "opening_range_pct",
            "gap",
        ]
    ],
    on=["ticker", "date"],
    how="left",
)

equity = INITIAL_CAPITAL
trades = []

for (ticker, date), day in df.groupby(["ticker", "date"]):
    day = day.sort_values("datetime").copy()

    opening_range_pct = day["opening_range_pct"].iloc[0]
    gap = day["gap"].iloc[0]

    if pd.isna(opening_range_pct) or pd.isna(gap):
        continue

    if opening_range_pct > MAX_OPENING_RANGE:
        continue

    if gap < MIN_GAP:
        continue

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

    entry_price = entry_row["close"]
    stop_price = entry_row["opening_low"]

    risk = entry_price - stop_price

    if risk <= 0:
        continue

    target_price = entry_price + R_MULTIPLE * risk

    after_entry = day[day["datetime"] > entry_row["datetime"]].copy()

    exit_price = day.iloc[-1]["close"]
    exit_reason = "close"

    for _, row in after_entry.iterrows():
        if row["low"] <= stop_price:
            exit_price = stop_price
            exit_reason = "stop"
            break

        if row["high"] >= target_price:
            exit_price = target_price
            exit_reason = "target"
            break

    gross_return = exit_price / entry_price - 1
    net_return = gross_return - COST_PER_TRADE

    pnl = equity * POSITION_SIZE * net_return
    equity += pnl

    trades.append({
        "date": date,
        "ticker": ticker,
        "gap": gap,
        "opening_range_pct": opening_range_pct,
        "exit_reason": exit_reason,
        "net_return": net_return,
        "pnl": pnl,
        "equity": equity,
    })


trades = pd.DataFrame(trades)

print("\n=== ORB TICKER ATTRIBUTION ===")

if len(trades) == 0:
    print("No trades found.")
else:
    summary = (
        trades.groupby("ticker")
        .agg(
            trades=("net_return", "count"),
            avg_trade=("net_return", "mean"),
            win_rate=("net_return", lambda x: (x > 0).mean()),
            total_return=("net_return", "sum"),
        )
        .sort_values("total_return", ascending=False)
    )

    print(summary)

    print("\n=== BEST TICKERS ===")
    print(summary.head(10))

    print("\n=== WORST TICKERS ===")
    print(summary.tail(10))