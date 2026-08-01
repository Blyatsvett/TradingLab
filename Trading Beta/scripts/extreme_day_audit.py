from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio

df = build_alpha(load_prices())

eq, ret, trades, history = simulate_portfolio(df)

print("\n=== TOP 10 BEST PORTFOLIO DAYS ===")
print(ret.sort_values("daily_return", ascending=False).head(10))

print("\n=== TOP 10 WORST PORTFOLIO DAYS ===")
print(ret.sort_values("daily_return").head(10))

best_day = ret.sort_values("daily_return", ascending=False).iloc[0]["date"]

print("\n=== HOLDINGS ON BEST DAY ===")
print(trades[trades["date"] == best_day].sort_values("return", ascending=False))

print("\n=== BIGGEST STOCK RETURN CONTRIBUTIONS ===")
trades["contribution"] = trades["weight"] * trades["return"]
print(trades.sort_values("contribution", ascending=False).head(20))

print("\n=== CONTRIBUTION BY TICKER ===")
print(
    trades.groupby("ticker")["contribution"]
    .sum()
    .sort_values(ascending=False)
)