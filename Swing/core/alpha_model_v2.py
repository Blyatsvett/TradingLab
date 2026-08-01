import pandas as pd


def add_features(df):
    df = df.copy()

    # -------------------------
    # Trend feature
    # -------------------------
    df["trend"] = (df["close"] / df["sma100"] - 1)

    # Cross-sectional normalization per day
    df["trend_z"] = df.groupby("date")["trend"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )

    # -------------------------
    # Volatility feature
    # -------------------------
    df["vol_z"] = df.groupby("date")["volatility"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )

    return df

    # -------------------------
    # Calcu
    # -------------------------


def calculate_score(row):
    score = 0.0

    if pd.notna(row.get("sma100")):
        score += (row["close"] / row["sma100"] - 1) * 5

    if pd.notna(row.get("volatility")) and row["volatility"] > 0:
        score += -row["volatility"] * 2

    return score


def add_normalized_score(df):
    df = df.copy()

    df["score"] = df.apply(calculate_score, axis=1)

    # CROSS-SECTIONAL NORMALIZATION (per date)
    df["score_z"] = df.groupby("date")["score"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )

    return df