from core.data_loader import load_prices
from core.metrics import performance_summary
from core.rebalance_simulator import simulate_rebalance_frequency


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()

# -------------------------
# Mean reversion factors
# -------------------------
df["return_1"] = df.groupby("ticker")["return"].shift(0)
df["return_3"] = df.groupby("ticker")["close"].pct_change(3)
df["return_5"] = df.groupby("ticker")["close"].pct_change(5)

# Negative = buy recent losers
df["reversal_1"] = -df["return_1"]
df["reversal_3"] = -df["return_3"]
df["reversal_5"] = -df["return_5"]

for col in ["reversal_1", "reversal_3", "reversal_5"]:
    df[col + "_z"] = zscore_by_date(df, col)

tests = {
    "reversal_1": df["reversal_1_z"],
    "reversal_3": df["reversal_3_z"],
    "reversal_5": df["reversal_5_z"],
}

for name, score in tests.items():
    print("\n" + "=" * 60)
    print(f"MEAN REVERSION TEST: {name}")
    print("=" * 60)

    test_df = df.copy()
    test_df["alpha"] = score
    test_df["alpha"] = test_df["alpha"].fillna(0)

    # Keep same no-bear filter for fair comparison
    test_df = test_df[test_df["regime"] != "bear"].copy()

    equity_curve, daily_returns = simulate_rebalance_frequency(
        test_df,
        top_n=2,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)


# -------------------------
# Year-by-year test for best candidates
# -------------------------
for factor in ["reversal_1", "reversal_3", "reversal_5"]:
    print("\n" + "#" * 60)
    print(f"YEARLY STABILITY: {factor}")
    print("#" * 60)

    test_df = df.copy()
    test_df["alpha"] = test_df[factor + "_z"].fillna(0)
    test_df = test_df[test_df["regime"] != "bear"].copy()

    for year in sorted(test_df["date"].dt.year.unique()):
        print("\n" + "-" * 60)
        print(f"{factor} | {year}")
        print("-" * 60)

        year_df = test_df[test_df["date"].dt.year == year].copy()

        equity_curve, daily_returns = simulate_rebalance_frequency(
            year_df,
            top_n=2,
            rebalance_every=3,
            cost_per_rebalance=0.0005,
        )

        performance_summary(equity_curve, daily_returns)