from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.overnight_simulator import simulate_overnight_execution
from core.metrics import performance_summary


df = load_prices()
df = build_alpha(df)

equity_curve, daily_returns, trade_log, portfolio_history = simulate_overnight_execution(
    df,
    top_n=10,
)

performance_summary(equity_curve, daily_returns)

print("\n=== TRADE LOG SAMPLE ===")
print(trade_log.tail())

print("\n=== PORTFOLIO HISTORY SAMPLE ===")
print(portfolio_history.tail())