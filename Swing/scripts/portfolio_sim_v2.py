import sqlite3
import pandas as pd

from core.alpha_model import calculate_score


# -------------------------
# LOAD DATA
# -------------------------
def load_data():
    conn = sqlite3.connect("data/prices.db")
    df = pd.read_sql("SELECT * FROM prices_enriched", conn)
    conn.close()

    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str).str.strip()

    return df


# -------------------------
# SCORE ENGINE
# -------------------------
def compute_scores(df):
    df = df.copy()
    df["score"] = df.apply(calculate_score, axis=1)
    return df


# -------------------------
# PORTFOLIO SELECTION
# -------------------------
def select_portfolio(df, top_n=5):
    if len(df) == 0:
        return df

    return (
        df.sort_values("score", ascending=False)
          .head(top_n)
          .copy()
    )


# -------------------------
# WEIGHTING (EQUAL WEIGHT FOR STABILITY)
# -------------------------
import numpy as np

def compute_weights(df):
    df = df.copy()

    x = df["score_z"].values
    exp_x = np.exp(x - np.max(x))  # numerical stability

    df["weight"] = exp_x / exp_x.sum()

    return df

# -------------------------
# SIMULATION ENGINE
# -------------------------
def simulate_portfolio(df, top_n=5):

    equity = 10000
    equity_history = []

    dates = sorted(df["date"].unique())

    print("\nRunning simulation...\n")
    print(f"Trading days: {len(dates)}\n")

    for i in range(len(dates) - 1):

        today = dates[i]
        tomorrow = dates[i + 1]

        # -------------------------
        # DATA SPLIT
        # -------------------------
        today_data = df[df["date"] == today]
        next_data = df[df["date"] == tomorrow][["ticker", "return"]]

        if len(today_data) == 0 or len(next_data) == 0:
            continue

        # -------------------------
        # PORTFOLIO SELECTION
        # -------------------------
        selected = today_data.sort_values("score_z", ascending=False).head(top_n)

        if len(selected) == 0:
            continue

        # -------------------------
        # CLEAN TICKERS
        # -------------------------
        selected["ticker"] = selected["ticker"].astype(str).str.strip()
        next_data["ticker"] = next_data["ticker"].astype(str).str.strip()

        # -------------------------
        # MERGE (SAFE VERSION)
        # -------------------------
        merged = selected.merge(
            next_data,
            on="ticker",
            how="left",
            suffixes=("", "_next")
        )

        # -------------------------
        # RETURN FIX (CRITICAL STABILITY PATCH)
        # -------------------------
        if "return" not in merged.columns:
            if "return_next" in merged.columns:
                merged["return"] = merged["return_next"]
            else:
                merged["return"] = 0

        merged["return"] = merged["return"].fillna(0)

        if len(merged) == 0:
            continue

        # -------------------------
        # WEIGHTS
        # -------------------------
        merged = compute_weights(merged)

        # -------------------------
        # DAILY RETURN
        # -------------------------
        daily_return = (merged["return"] * merged["weight"]).sum()

        # -------------------------
        # EQUITY UPDATE
        # -------------------------
        equity *= (1 + daily_return)

        equity_history.append({
            "date": tomorrow,
            "equity": equity
        })

    return pd.DataFrame(equity_history)


# -------------------------
# RUN SCRIPT
# -------------------------
if __name__ == "__main__":

    df = load_data()
    df = compute_scores(df)

    equity_curve = simulate_portfolio(df)

    print("\n=== EQUITY CURVE (LAST 5 DAYS) ===")
    print(equity_curve.tail())

    if len(equity_curve) > 0:
        final_equity = equity_curve["equity"].iloc[-1]
        total_return = (final_equity / 10000 - 1) * 100

        print("\n=== PERFORMANCE SUMMARY ===")
        print(f"Final equity: {final_equity:.2f} SEK")
        print(f"Return: {total_return:.2f}%")