import pandas as pd


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def build_alpha(df):
    df = df.copy()

    # -------------------------
    # Trend / momentum features
    # -------------------------
    df["trend_50"] = df["close"] / df["sma50"] - 1
    df["trend_100"] = df["close"] / df["sma100"] - 1

    df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
    df["momentum_20"] = df.groupby("ticker")["close"].pct_change(20)

    # -------------------------
    # Short-term continuation
    # -------------------------
    df["continuation_1"] = df.groupby("ticker")["return"].shift(0)

    # -------------------------
    # Volume pressure
    # -------------------------
    df["volume_sma20"] = df.groupby("ticker")["volume"].transform(
        lambda x: x.rolling(20).mean()
    )

    df["volume_ratio"] = df["volume"] / df["volume_sma20"]

    # -------------------------
    # Volatility factor
    # -------------------------
    df["volatility_factor"] = df["volatility"]

    # -------------------------
    # Normalize all factors per day
    # -------------------------
    factor_cols = [
        "trend_50",
        "trend_100",
        "momentum_5",
        "momentum_20",
        "continuation_1",
        "volume_ratio",
        "volatility_factor",
    ]

    for col in factor_cols:
        df[col + "_z"] = zscore_by_date(df, col)

    # -------------------------
    # Combined overnight alpha v3
    # -------------------------
    df["score"] = (
            0.40 * df["momentum_5_z"]
        + 0.30 * df["trend_50_z"]
        + 0.20 * df["continuation_1_z"]
        + 0.10 * df["momentum_20_z"]    
    )

    df["alpha"] = zscore_by_date(df, "score")
    df["alpha"] = df["alpha"].fillna(0)

    return df