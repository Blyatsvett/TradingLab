from core.data_loader import load_prices
from core.metrics import performance_summary
from core.overnight_simulator import simulate_overnight_execution


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()

# -------------------------
# Alpha
# -------------------------
df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

# -------------------------
# Market regime
# -------------------------
market = (
    df.groupby("date")["close"]
    .mean()
    .reset_index()
)

market = market.rename(columns={"close": "market_close"})

market["market_sma50"] = market["market_close"].rolling(50).mean()
market["market_sma200"] = market["market_close"].rolling(200).mean()

market["market_regime"] = "sideways"
market.loc[market["market_sma50"] > market["market_sma200"], "market_regime"] = "bull"
market.loc[market["market_sma50"] < market["market_sma200"], "market_regime"] = "bear"

# Merge regime into stock dataframe
df = df.merge(
    market[["date", "market_regime"]],
    on="date",
    how="left"
)

# Filter out bear market
filtered_df = df[df["market_regime"] != "bear"].copy()

print("\n" + "=" * 60)
print("MARKET REGIME FILTER TEST")
print("=" * 60)

equity_curve, daily_returns, _, _ = simulate_overnight_execution(
    filtered_df,
    top_n=3,
)

performance_summary(equity_curve, daily_returns)