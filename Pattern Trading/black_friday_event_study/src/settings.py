from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "output"
DB_PATH = ROOT / "event_study.db"

COMPANIES_CSV = CONFIG_DIR / "companies.csv"

# Benchmark ETFs downloaded alongside the company prices.
BENCHMARK_TICKERS = ["SPY", "XRT"]

# Each model lists the benchmark-return columns used in its regression.
FACTOR_MODELS = {
    "SPY": ["SPY_return"],
    "XRT": ["XRT_return"],
    "SPY_XRT": ["SPY_return", "XRT_return"],
}

# Download enough history to estimate beta before the first 2010 event.
DOWNLOAD_START = "2008-01-01"
DOWNLOAD_END = "2026-02-01"

EVENT_START_YEAR = 2010
EVENT_END_YEAR = 2025

ESTIMATION_START = -250
ESTIMATION_END = -61
PANEL_START = -60
PANEL_END = 30

MIN_ESTIMATION_OBSERVATIONS = 120
MIN_EVENT_YEARS = 8

EVENT_WINDOWS = {
    "Early_positioning": (-60, -21),
    "Pre_event": (-20, -6),

    # Separates likely retailer-earnings days from the shopping event.
    "Pre_Thanksgiving_Earnings": (-5, -4),
    "Thanksgiving_week": (-3, -1),
    "Black_Friday": (0, 0),
    "Cyber_Monday": (1, 1),
    "Consumer_event": (-3, 1),

    "Early_post": (2, 10),
    "Late_post": (11, 30),
}