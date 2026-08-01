from core.data_loader import load_prices
from core.metrics import performance_summary
from core.rebalance_simulator import simulate_rebalance_frequency


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def build_alpha_v2(df):
    df = df.copy()

    df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
    df["trend_50"] = df["close"] / df["sma50"] - 1

    df["momentum_5_z"] = zscore_by_date(df, "momentum_5")
    df["trend_50_z"] = zscore_by_date(df, "trend_50")

    df["alpha"] = 0.0

    df.loc[df["regime"] == "bull", "alpha"] = (
        0.80 * df["momentum_5_z"]
        + 0.20 * df["trend_50_z"]
    )

    df.loc[df["regime"] == "sideways", "alpha"] = df["momentum_5_z"]

    df = df[df["regime"] != "bear"].copy()
    df["alpha"] = df["alpha"].fillna(0)

    return df


df = load_prices()
df = build_alpha_v2(df)

years = sorted(df["date"].dt.year.unique())

for year in years:
    print("\n" + "=" * 60)
    print(f"WALK-FORWARD YEAR TEST: {year}")
    print("=" * 60)

    test_df = df[df["date"].dt.year == year].copy()

    equity_curve, daily_returns = simulate_rebalance_frequency(
        test_df,
        top_n=2,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)