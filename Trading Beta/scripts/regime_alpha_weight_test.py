from core.data_loader import load_prices
from core.metrics import performance_summary

import pandas as pd


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def compute_equal_weights(selected):
    selected = selected.copy()
    selected["weight"] = 1.0 / len(selected)
    return selected


def compute_alpha_weights(selected):
    selected = selected.copy()

    min_alpha = selected["alpha"].min()
    selected["alpha_shifted"] = selected["alpha"] - min_alpha + 1e-9

    selected["weight"] = selected["alpha_shifted"] / selected["alpha_shifted"].sum()
    return selected


def compute_capped_alpha_weights(selected, max_weight=0.60):
    selected = compute_alpha_weights(selected)

    selected["weight"] = selected["weight"].clip(upper=max_weight)
    selected["weight"] = selected["weight"] / selected["weight"].sum()

    return selected


def simulate_weight_model(
    df,
    weight_model="equal",
    top_n=2,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
    initial_capital=10000,
):
    equity = initial_capital
    equity_history = []
    return_history = []

    dates = sorted(df["date"].unique())
    current_portfolio = None

    for i in range(len(dates)):
        signal_day = dates[i]

        should_rebalance = current_portfolio is None or i % rebalance_every == 0

        if should_rebalance:
            signal_data = df[df["date"] == signal_day].copy()

            selected = (
                signal_data
                .sort_values("alpha", ascending=False)
                .head(top_n)
                .copy()
            )

            if len(selected) == 0:
                continue

            if weight_model == "equal":
                selected = compute_equal_weights(selected)
            elif weight_model == "alpha":
                selected = compute_alpha_weights(selected)
            elif weight_model == "capped_alpha":
                selected = compute_capped_alpha_weights(selected, max_weight=0.60)
            else:
                raise ValueError(f"Unknown weight_model: {weight_model}")

            current_portfolio = selected[["ticker", "weight"]].copy()
            cost = cost_per_rebalance
        else:
            cost = 0.0

        return_data = df[df["date"] == signal_day][
            ["ticker", "overnight_return"]
        ].copy()

        merged = current_portfolio.merge(return_data, on="ticker", how="left")
        merged["overnight_return"] = merged["overnight_return"].fillna(0)

        daily_return = (merged["weight"] * merged["overnight_return"]).sum()
        net_return = daily_return - cost

        equity *= (1 + net_return)

        equity_history.append({"date": signal_day, "equity": equity})
        return_history.append({"date": signal_day, "daily_return": net_return})

    return pd.DataFrame(equity_history), pd.DataFrame(return_history)


df = load_prices()

# -------------------------
# Build Regime Alpha V2
# -------------------------
df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["trend_50"] = df["close"] / df["sma50"] - 1

df["momentum_5_z"] = zscore_by_date(df, "momentum_5")
df["trend_50_z"] = zscore_by_date(df, "trend_50")

df["alpha"] = 0.0

df.loc[df["regime"] == "bull", "alpha"] = (
    0.80 * df["momentum_5_z"]
    + 0.20 * df["trend_50_z"]
)

df.loc[df["regime"] == "sideways", "alpha"] = df["momentum_5_z"]

df = df[df["regime"] != "bear"].copy()
df["alpha"] = df["alpha"].fillna(0)


# -------------------------
# Test weight models
# -------------------------
for model in ["equal", "alpha", "capped_alpha"]:
    print("\n" + "=" * 60)
    print(f"REGIME ALPHA WEIGHT TEST: {model.upper()}")
    print("=" * 60)

    equity_curve, daily_returns = simulate_weight_model(
        df,
        weight_model=model,
        top_n=2,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)