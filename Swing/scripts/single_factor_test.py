from core.data_loader import load_prices
from core.metrics import performance_summary
from core.overnight_simulator import simulate_overnight_execution


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def add_factor_features(df):
    df = df.copy()

    df["trend_50"] = df["close"] / df["sma50"] - 1
    df["trend_100"] = df["close"] / df["sma100"] - 1

    df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
    df["momentum_20"] = df.groupby("ticker")["close"].pct_change(20)

    df["continuation_1"] = df.groupby("ticker")["return"].shift(0)

    df["volume_sma20"] = df.groupby("ticker")["volume"].transform(
        lambda x: x.rolling(20).mean()
    )
    df["volume_ratio"] = df["volume"] / df["volume_sma20"]

    return df


def test_factor(df, factor_name, ascending=False):
    test_df = df.copy()

    raw_factor = test_df[factor_name]

    if ascending:
        raw_factor = -raw_factor

    test_df["alpha"] = zscore_by_date(
        test_df.assign(_factor=raw_factor),
        "_factor"
    )

    print("\n" + "=" * 60)
    print(f"FACTOR TEST: {factor_name} | ascending={ascending}")
    print("=" * 60)

    equity_curve, daily_returns, _, _ = simulate_overnight_execution(
        test_df,
        top_n=10,
    )

    performance_summary(equity_curve, daily_returns)


df = load_prices()
df = add_factor_features(df)

tests = [
    ("momentum_5", False),
    ("momentum_20", False),
    ("trend_50", False),
    ("trend_100", False),
    ("continuation_1", False),
    ("volume_ratio", False),
    ("volume_ratio", True),
    ("volatility", False),
    ("volatility", True),
]

for factor_name, ascending in tests:
    test_factor(df, factor_name, ascending)