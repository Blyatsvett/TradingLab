import pandas as pd


def select_portfolio(df, top_n=10):
    """
    Select the highest-ranked stocks based on alpha.
    """

    if len(df) == 0:
        return df.copy()

    return (
        df.sort_values("alpha", ascending=False)
        .head(top_n)
        .copy()
    )


def compute_weights(df):
    """
    Equal-weight selected stocks.

    This prevents one stock from dominating the portfolio.
    """

    df = df.copy()

    if len(df) == 0:
        return df

    df["weight"] = 1.0 / len(df)

    return df