"""Research-only snapshot of frozen ORB metadata.

This file is deliberately separate from the production Intraday package.
Changing it cannot alter the production ORB scanner or paper-trading system.
"""

ORB_STRATEGY_VERSION = "ORB_BEST_BASKET_V1"

ORB_ALLOWED_TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "SEB-A.ST",
    "ATCO-A.ST",
]

ORB_COST_PER_TRADE = 0.0005
ORB_INITIAL_CAPITAL = 10000
ORB_POSITION_SIZE = 0.10

RESEARCH_CONFIG_SOURCE = "FROZEN_ORB_RESEARCH_SNAPSHOT"
