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


def run_test(min_rvol):
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
            opening_volume=("volume", "sum"),
            day_open=("open", "first"),
        )
        .reset_index()
    )

    orb["opening_range_pct"] = orb["opening_high"] / orb["opening_low"] - 1

    orb["avg_opening_volume_20"] = (
        orb.groupby("ticker")["opening_volume"]
        .transform(lambda x: x.shift(1).rolling(20).mean())
    )

    orb["relative_volume"] = (
        orb["opening_volume"] / orb["avg_opening_volume_20"]
    )

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
                "relative_volume",
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
        relative_volume = day["relative_volume"].iloc[0]
        gap = day["gap"].iloc[0]

        if pd.isna(opening_range_pct) or pd.isna(relative_volume) or pd.isna(gap):
            continue

        if opening_range_pct > MAX_OPENING_RANGE:
            continue

        if gap < MIN_GAP:
            continue

        if relative_volume < min_rvol:
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
            "relative_volume": relative_volume,
            "opening_range_pct": opening_range_pct,
            "exit_reason": exit_reason,
            "net_return": net_return,
            "pnl": pnl,
            "equity": equity,
        })

    trades = pd.DataFrame(trades)

    print("\n" + "=" * 60)
    print(f"ORB RELATIVE VOLUME TEST: min RVOL {min_rvol:.2f}")
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


for rvol in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
    run_test(rvol)