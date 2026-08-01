from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.execution_simulator import simulate_intraday_execution
from core.metrics import performance_summary


df = load_prices()
df = build_alpha(df)

equity_curve, daily_returns, trade_log, portfolio_history = simulate_intraday_execution(
    df,
    top_n=10,
)

performance_summary(equity_curve, daily_returns)

print("\n=== TRADE LOG SAMPLE ===")
print(trade_log.head(20))
print(trade_log.columns)

print("\n=== PORTFOLIO HISTORY SAMPLE ===")
print(portfolio_history.tail())