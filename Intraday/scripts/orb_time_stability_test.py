import sqlite3
import pandas as pd


ALLOWED_TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "ATCO-A.ST",
    "EVO.ST",
    "SEB-A.ST",
    "ABB.ST",
]

COST_PER_TRADE = 0.0005
BREAKOUT_START = pd.to_datetime("09:35").time()
BREAKOUT_END = pd.to_datetime("11:00").time()
R_MULTIPLE = 1.0
MAX_OPENING_RANGE = 0.02
MIN_GAP = 0.0


conn = sqlite3.connect("data/intraday_prices.db")
df = pd.read_sql("SELECT * FROM intraday_prices", conn)
conn.close()

df = df[df["ticker"].isin(ALLOWED_TICKERS)].copy()

df["datetime"] = pd.to_datetime(df["datetime"])
df["date"] = df["datetime"].dt.date
df["week"] = df["datetime"].dt.to_period("W").astype(str)
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

    trades.append({
        "date": date,
        "week": entry_row["datetime"].to_period("W").strftime("%Y-%m-%d/%Y-%m-%d"),
        "ticker": ticker,
        "exit_reason": exit_reason,
        "net_return": net_return,
    })


trades = pd.DataFrame(trades)

print("\n=== ORB TIME STABILITY TEST ===")

if len(trades) == 0:
    print("No trades found.")
else:
    print("\n=== DAILY RESULTS ===")
    daily = (
        trades.groupby("date")
        .agg(
            trades=("net_return", "count"),
            avg_trade=("net_return", "mean"),
            total_return=("net_return", "sum"),
            win_rate=("net_return", lambda x: (x > 0).mean()),
        )
        .sort_index()
    )
    print(daily)

    print("\n=== WEEKLY RESULTS ===")
    weekly = (
        trades.groupby("week")
        .agg(
            trades=("net_return", "count"),
            avg_trade=("net_return", "mean"),
            total_return=("net_return", "sum"),
            win_rate=("net_return", lambda x: (x > 0).mean()),
        )
        .sort_index()
    )
    print(weekly)

    print("\n=== SUMMARY ===")
    print(f"Trades: {len(trades)}")
    print(f"Positive days: {(daily['total_return'] > 0).mean():.2%}")
    print(f"Positive weeks: {(weekly['total_return'] > 0).mean():.2%}")
    print(f"Total return sum: {trades['net_return'].sum():.2%}")