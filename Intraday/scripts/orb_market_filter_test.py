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

INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10
COST_PER_TRADE = 0.0005

BREAKOUT_START = pd.to_datetime("09:35").time()
BREAKOUT_END = pd.to_datetime("11:00").time()

R_MULTIPLE = 1.0
MAX_OPENING_RANGE = 0.02
MIN_GAP = 0.0


def run_test(require_market_positive):
    conn = sqlite3.connect("data/intraday_prices.db")
    df = pd.read_sql("SELECT * FROM intraday_prices", conn)
    conn.close()

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.time

    # Synthetic market proxy from all available intraday tickers
    market_opening = df[
        (df["time"] >= pd.to_datetime("09:00").time()) &
        (df["time"] <= pd.to_datetime("09:30").time())
    ].copy()

    market = (
        market_opening.groupby(["date", "ticker"])
        .agg(
            first_open=("open", "first"),
            last_close=("close", "last"),
        )
        .reset_index()
    )

    market["opening_return"] = market["last_close"] / market["first_open"] - 1

    market_daily = (
        market.groupby("date")["opening_return"]
        .mean()
        .reset_index()
        .rename(columns={"opening_return": "market_opening_return"})
    )

    df = df[df["ticker"].isin(ALLOWED_TICKERS)].copy()

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

    df = df.merge(market_daily, on="date", how="left")

    equity = INITIAL_CAPITAL
    trades = []

    for (ticker, date), day in df.groupby(["ticker", "date"]):
        day = day.sort_values("datetime").copy()

        opening_range_pct = day["opening_range_pct"].iloc[0]
        gap = day["gap"].iloc[0]
        market_opening_return = day["market_opening_return"].iloc[0]

        if (
            pd.isna(opening_range_pct)
            or pd.isna(gap)
            or pd.isna(market_opening_return)
        ):
            continue

        if require_market_positive and market_opening_return <= 0:
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

        entry_time = entry_row["datetime"]
        entry_price = entry_row["close"]
        stop_price = entry_row["opening_low"]

        risk = entry_price - stop_price
        if risk <= 0:
            continue

        target_price = entry_price + R_MULTIPLE * risk

        after_entry = day[day["datetime"] > entry_time].copy()

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
            "market_opening_return": market_opening_return,
            "gap": gap,
            "opening_range_pct": opening_range_pct,
            "exit_reason": exit_reason,
            "net_return": net_return,
            "pnl": pnl,
            "equity": equity,
        })

    trades = pd.DataFrame(trades)

    label = "MARKET POSITIVE ONLY" if require_market_positive else "NO MARKET FILTER"

    print("\n" + "=" * 60)
    print(f"ORB MARKET FILTER TEST: {label}")
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


run_test(require_market_positive=False)
run_test(require_market_positive=True)