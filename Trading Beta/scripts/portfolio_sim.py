import sqlite3
import pandas as pd
import numpy as np

# ----------------------------
# LOAD DATA
# ----------------------------
conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["date", "ticker"])

# ----------------------------
# RETURNS (NO LOOKAHEAD)
# ----------------------------
# next-day return aligned to today’s signal
df["ret"] = df.groupby("ticker")["close"].pct_change().shift(-1)

# ----------------------------
# STRATEGY MAP
# ----------------------------
strategy_map = {
    "bull": ("sma20", "sma100", 5),
    "bear": ("sma10", "sma50", 3),
    "sideways": ("sma30", "sma100", 2)
}

# ----------------------------
# PARAMETERS
# ----------------------------
initial_capital = 10_000
turnover_cost = 0.001  # 0.1% friction per asset

# ----------------------------
# STATE
# ----------------------------
equity = initial_capital
equity_curve = []
drawdowns = []

peak = initial_capital

# ----------------------------
# SIMULATION LOOP
# ----------------------------
for date, day_data in df.groupby("date"):

    day_data = day_data.copy()

    if len(day_data) == 0 or "regime" not in day_data.columns:
        continue

    # ----------------------------
    # REGIME SELECTION
    # ----------------------------
    regime = day_data["regime"].value_counts().idxmax()
    fast, slow, top_n = strategy_map[regime]

    # ----------------------------
    # SIGNAL SCORING
    # ----------------------------
    def score(row):
        s = 0

        if row["close"] > row[slow]:
            s += 20

        if row[fast] > row[slow]:
            s += 20

        if not np.isnan(row["ret"]) and row["ret"] > 0:
            s += 10

        return s

    day_data["score"] = day_data.apply(score, axis=1)

    # ----------------------------
    # SELECT TOP ASSETS
    # ----------------------------
    selected = (
        day_data.groupby("ticker")["score"]
        .mean()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )

    selected_data = day_data[day_data["ticker"].isin(selected)].copy()

    if selected_data.empty:
        continue

    # ----------------------------
    # POSITION WEIGHTS (EQUAL WEIGHT)
    # ----------------------------
    weights = 1 / len(selected)

    # ----------------------------
    # PORTFOLIO RETURN
    # ----------------------------
    asset_returns = selected_data["ret"].fillna(0)

    position_return = (asset_returns * weights).sum()

    # ----------------------------
    # TURNOVER COST (REALISM)
    # ----------------------------
    position_return -= turnover_cost * len(selected)

    # ----------------------------
    # UPDATE EQUITY
    # ----------------------------
    equity *= (1 + position_return)
    equity_curve.append(equity)

    # ----------------------------
    # DRAWDOWN
    # ----------------------------
    peak = max(equity_curve)
    dd = (equity - peak) / peak
    drawdowns.append(dd)

# ----------------------------
# RESULTS
# ----------------------------
total_return = (equity / initial_capital - 1) * 100
max_dd = min(drawdowns) * 100 if drawdowns else 0

print("\n=== PORTFOLIO RESULTS ===")
print(f"Final equity: {equity:.2f} SEK")
print(f"Return: {total_return:.2f}%")
print(f"Max drawdown: {max_dd:.2f}%")