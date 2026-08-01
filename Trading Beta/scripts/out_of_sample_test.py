from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio
from core.metrics import performance_summary


# -------------------------
# LOAD DATA
# -------------------------
df = load_prices()
df = build_alpha(df)

# -------------------------
# SPLIT DATA
# -------------------------
train_df = df[df["date"] < "2023-01-01"].copy()
test_df = df[df["date"] >= "2023-01-01"].copy()

print("\n")
print("=" * 60)
print("TRAIN PERIOD: 2020-2022")
print("=" * 60)

train_equity, train_returns, _, _ = simulate_portfolio(train_df)

performance_summary(
    train_equity,
    train_returns
)

print("\n")
print("=" * 60)
print("TEST PERIOD: 2023-2024")
print("=" * 60)

test_equity, test_returns, _, _ = simulate_portfolio(test_df)

performance_summary(
    test_equity,
    test_returns
)