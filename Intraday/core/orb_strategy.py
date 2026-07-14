import sqlite3
import pandas as pd
from Intraday.core.paths import INTRADAY_DB

def load_intraday_prices(db_path=INTRADAY_DB):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM intraday_prices", conn)
    conn.close()

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.time

    return df


def build_orb_trades(
    df,
    allowed_tickers,
    breakout_start="09:35",
    breakout_end="11:00",
    r_multiple=1.0,
    max_opening_range=0.02,
    min_gap=0.0,
    cost_per_trade=0.0005,
):
    df = df[df["ticker"].isin(allowed_tickers)].copy()

    breakout_start = pd.to_datetime(breakout_start).time()
    breakout_end = pd.to_datetime(breakout_end).time()

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

        if opening_range_pct > max_opening_range:
            continue

        if gap < min_gap:
            continue

        trade_window = day[
            (day["time"] >= breakout_start) &
            (day["time"] <= breakout_end)
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
        net_return = gross_return - cost_per_trade

        trades.append({
            "date": date,
            "ticker": ticker,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "exit_reason": exit_reason,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "exit_price": exit_price,
            "gap": gap,
            "opening_range_pct": opening_range_pct,
            "gross_return": gross_return,
            "net_return": net_return,
        })

    return pd.DataFrame(trades)


def simulate_orb_equity(
    trades,
    initial_capital=10000,
    position_size=0.10,
):
    equity = initial_capital
    equity_curve = []

    trades = trades.copy()

    for idx, row in trades.iterrows():
        pnl = equity * position_size * row["net_return"]
        equity += pnl

        trades.loc[idx, "pnl"] = pnl
        trades.loc[idx, "equity"] = equity

        equity_curve.append({
            "date": row["date"],
            "equity": equity,
        })

    return trades, pd.DataFrame(equity_curve)


def orb_summary(trades, equity_curve, initial_capital=10000):
    if len(trades) == 0:
        print("No trades found.")
        return

    final_equity = equity_curve["equity"].iloc[-1]
    total_return = final_equity / initial_capital - 1
    win_rate = (trades["net_return"] > 0).mean()
    avg_trade = trades["net_return"].mean()

    print("\n=== ORB SUMMARY ===")
    print(f"Trades       : {len(trades)}")
    print(f"Final equity : {final_equity:.2f} SEK")
    print(f"Return       : {total_return:.2%}")
    print(f"Win rate     : {win_rate:.2%}")
    print(f"Avg trade    : {avg_trade:.4%}")

    print("\n=== BY TICKER ===")
    print(
        trades.groupby("ticker")["net_return"]
        .agg(["count", "mean"])
        .sort_values("mean", ascending=False)
    )

    print("\n=== EXIT REASONS ===")
    print(trades["exit_reason"].value_counts())