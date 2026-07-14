from pathlib import Path

INTRADAY_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = INTRADAY_DIR / "data"

DATA_DIR.mkdir(exist_ok=True)

INTRADAY_DB = DATA_DIR / "intraday_prices.db"

ORB_SIGNALS_LATEST = DATA_DIR / "orb_signals_latest.csv"
ORB_SIGNAL_HISTORY = DATA_DIR / "orb_signal_history.csv"

PAPER_TRADES = DATA_DIR / "paper_trades.csv"
PAPER_EQUITY_CURVE = DATA_DIR / "paper_equity_curve.csv"