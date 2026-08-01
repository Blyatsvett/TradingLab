import os
import yfinance as yf

os.makedirs("data/raw", exist_ok=True)

tickers = [
    "VOLV-B.ST",
    "ATCO-A.ST",
    "INVE-B.ST",
    "EVO.ST",
    "ERIC-B.ST"
]

for ticker in tickers:
    print(f"Downloading {ticker}...")

    df = yf.download(
        ticker,
        start="2020-01-01",
        end="2025-01-01",
        auto_adjust=True,
        progress=False
    )

    filename = ticker.replace(".ST", "")

    path = f"data/raw/{filename}.csv"
    df.to_csv(path)

    print(f"Saved {ticker} → {path} ({len(df)} rows)")