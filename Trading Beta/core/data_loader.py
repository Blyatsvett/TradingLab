import sqlite3
import pandas as pd


def load_prices(db_path="data/prices.db"):
    """
    Load enriched price data from the SQLite database.
    """

    conn = sqlite3.connect(db_path)

    df = pd.read_sql(
        "SELECT * FROM prices_enriched",
        conn
    )

    conn.close()

    # Convert date column
    df["date"] = pd.to_datetime(df["date"])

    # Clean ticker names
    df["ticker"] = (
        df["ticker"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # Sort for consistency
    df = df.sort_values(
        ["date", "ticker"]
    ).reset_index(drop=True)

    return df