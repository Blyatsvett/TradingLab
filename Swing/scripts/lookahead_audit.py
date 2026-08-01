from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.portfolio import select_portfolio, compute_weights

import pandas as pd


df = load_prices()
df = build_alpha(df)

dates = sorted(df["date"].unique())

audit_rows = []

for i in range(len(dates) - 1):

    today = dates[i]
    tomorrow = dates[i + 1]

    today_data = df[df["date"] == today].copy()
    tomorrow_data = df[df["date"] == tomorrow][["ticker", "return"]].copy()

    portfolio = select_portfolio(today_data, top_n=5)

    if len(portfolio) == 0:
        continue

    portfolio = compute_weights(portfolio)

    merged = portfolio.merge(
        tomorrow_data,
        on="ticker",
        how="left",
        suffixes=("", "_tomorrow")
    )

    merged["return"] = merged["return"].fillna(0)

    for _, row in merged.iterrows():
        audit_rows.append({
            "signal_date": today,
            "return_date": tomorrow,
            "ticker": row["ticker"],
            "alpha_used": row["alpha"],
            "weight": row["weight"],
            "next_day_return": row["return"],
        })


audit = pd.DataFrame(audit_rows)

print("\n=== LOOK-AHEAD AUDIT ===")
print(audit.head(10))
print(audit.tail(10))

print("\nSignal date always before return date?")
print((audit["signal_date"] < audit["return_date"]).all())

print("\nSample date differences:")
print((audit["return_date"] - audit["signal_date"]).describe())

print("\nColumns:")
print(audit.columns)