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
df = df.sort_values(["ticker", "date"])

# ----------------------------
# RETURNS (next day)
# ----------------------------
df["ret"] = df.groupby("ticker")["close"].pct_change().shift(-1)

# ----------------------------
# SCORE FUNCTION (same logic as portfolio)
# ----------------------------
def compute_score(row, fast, slow):
    score = 0

    if row["close"] > row[slow]:
        score += 20

    if row[fast] > row[slow]:
        score += 20

    if not np.isnan(row["ret"]) and row["ret"] > 0:
        score += 10

    return score

# ----------------------------
# BUILD DIAGNOSTICS TABLE
# ----------------------------
records = []

for date, day in df.groupby("date"):

    day = day.copy()

    if "regime" not in day.columns:
        continue

    regime = day["regime"].mode()[0]

    # same mapping as portfolio
    if regime == "bull":
        fast, slow, top_n = "sma20", "sma100", 5
    elif regime == "bear":
        fast, slow, top_n = "sma10", "sma50", 3
    else:
        fast, slow, top_n = "sma30", "sma100", 2

    day["score"] = day.apply(lambda r: compute_score(r, fast, slow), axis=1)

    selected = (
        day.groupby("ticker")["score"]
        .mean()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )

    for _, row in day.iterrows():

        records.append({
            "date": date,
            "ticker": row["ticker"],
            "regime": regime,
            "score": row["score"],
            "fast": fast,
            "slow": slow,
            "selected": int(row["ticker"] in selected),
            "ret": row["ret"]
        })

diag = pd.DataFrame(records)

# ----------------------------
# SAVE TO SQLITE
# ----------------------------
conn = sqlite3.connect("data/diagnostics.db")
diag.to_sql("diagnostics", conn, if_exists="replace", index=False)
conn.close()

print("Diagnostics DB built:", len(diag), "rows")