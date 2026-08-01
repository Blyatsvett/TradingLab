from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio
from core.metrics import performance_summary

import numpy as np


df = load_prices()

# -------------------------
# REAL ALPHA
# -------------------------
real_df = build_alpha(df)

print("\n" + "=" * 60)
print("REAL ALPHA")
print("=" * 60)

eq, ret, _, _ = simulate_portfolio(real_df)
performance_summary(eq, ret)


# -------------------------
# RANDOM ALPHA TESTS
# -------------------------
n_tests = 20
results = []

for seed in range(n_tests):

    random_df = df.copy()

    np.random.seed(seed)

    random_df["alpha"] = np.random.normal(
        0,
        1,
        len(random_df)
    )

    print("\n" + "=" * 60)
    print(f"RANDOM ALPHA TEST {seed + 1}/{n_tests}")
    print("=" * 60)

    eq, ret, _, _ = simulate_portfolio(random_df)

    final_equity = eq["equity"].iloc[-1]
    total_return = final_equity / 10000 - 1
    sharpe = (
        ret["daily_return"].mean()
        / ret["daily_return"].std()
        * np.sqrt(252)
    )

    results.append({
        "seed": seed,
        "final_equity": final_equity,
        "total_return": total_return,
        "sharpe": sharpe,
    })


print("\n" + "=" * 60)
print("RANDOM ALPHA SUMMARY")
print("=" * 60)

final_equities = [r["final_equity"] for r in results]
sharpes = [r["sharpe"] for r in results]

print(f"Random tests       : {n_tests}")
print(f"Avg final equity   : {np.mean(final_equities):,.2f} SEK")
print(f"Best final equity  : {np.max(final_equities):,.2f} SEK")
print(f"Worst final equity : {np.min(final_equities):,.2f} SEK")
print(f"Avg Sharpe         : {np.mean(sharpes):.2f}")
print(f"Best Sharpe        : {np.max(sharpes):.2f}")
print(f"Worst Sharpe       : {np.min(sharpes):.2f}")