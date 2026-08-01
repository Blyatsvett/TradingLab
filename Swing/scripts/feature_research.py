from core.data_loader import load_prices
from core.alpha_model import build_alpha

df = build_alpha(load_prices())

features = [
    "trend_50",
    "trend_100",
    "momentum_5",
    "momentum_20",
    "reversal_1",
    "volume_ratio",
    "volatility",
]

print("\n=== FEATURE CORRELATION WITH OVERNIGHT RETURN ===\n")

for col in features:
    subset = df[[col, "overnight_return"]].dropna()

    corr = subset[col].corr(subset["overnight_return"])

    print(f"{col:15} {corr:.6f}")