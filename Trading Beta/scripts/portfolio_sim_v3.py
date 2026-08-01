from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio
from core.metrics import performance_summary

df = load_prices()
df = build_alpha(df)

equity, returns, trades, history = simulate_portfolio(df, top_n=10)

performance_summary(equity, returns)