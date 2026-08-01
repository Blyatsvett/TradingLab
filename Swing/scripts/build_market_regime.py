from core.data_loader import load_prices
import pandas as pd


df = load_prices()

market = (
    df.groupby("date")["close"]
    .mean()
    .reset_index()
)

market = market.rename(columns={"close": "market_close"})

market["market_sma50"] = market["market_close"].rolling(50).mean()
market["market_sma200"] = market["market_close"].rolling(200).mean()

market["market_regime"] = "sideways"

market.loc[
    market["market_sma50"] > market["market_sma200"],
    "market_regime"
] = "bull"

market.loc[
    market["market_sma50"] < market["market_sma200"],
    "market_regime"
] = "bear"

print(market.tail(20))