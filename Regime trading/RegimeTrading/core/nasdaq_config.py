from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from RegimeTrading.core.paths import COLLECTOR_OUTPUT_DIR, MARKET_SOURCE_DIR, NASDAQ_RAW_DIR


NASDAQ_FORWARD_DB = MARKET_SOURCE_DIR / "nasdaq_forward_data.db"
NASDAQ_PROBE_DIR = NASDAQ_RAW_DIR / "probe"
NASDAQ_INCOMING_DIR = NASDAQ_RAW_DIR / "incoming"
NASDAQ_ARCHIVE_DIR = NASDAQ_RAW_DIR / "archive"

NASDAQ_COLLECTION_STATUS_CSV = COLLECTOR_OUTPUT_DIR / "nasdaq_collection_status.csv"
NASDAQ_INSTRUMENT_COVERAGE_CSV = COLLECTOR_OUTPUT_DIR / "nasdaq_instrument_coverage.csv"
NASDAQ_5M_BARS_LATEST_CSV = COLLECTOR_OUTPUT_DIR / "nasdaq_5m_bars_latest.csv"
NASDAQ_YAHOO_BAR_COMPARISON_CSV = COLLECTOR_OUTPUT_DIR / "nasdaq_yahoo_bar_comparison.csv"
NASDAQ_YAHOO_OR_COMPARISON_CSV = (
    COLLECTOR_OUTPUT_DIR / "nasdaq_yahoo_opening_range_comparison.csv"
)
NASDAQ_YAHOO_DECISION_COMPARISON_CSV = (
    COLLECTOR_OUTPUT_DIR / "nasdaq_yahoo_strategy_decision_comparison.csv"
)
NASDAQ_YAHOO_DECISION_SUMMARY_CSV = (
    COLLECTOR_OUTPUT_DIR / "nasdaq_yahoo_strategy_decision_summary.csv"
)

POST_TRADE_PAGE = (
    "https://tradereports.nasdaq.com/shares/trade-reports/post-trade"
)
REPORT_PREFIX = "NordicEquity-posttrade-"
STOCKHOLM_TIMEZONE = "Europe/Stockholm"
PRIMARY_MIC = "XSTO"
PRIMARY_TRADING_SYSTEM = "CLOB"
PRIMARY_CURRENCY = "SEK"
PRIMARY_PRICE_NOTATION = "MONE"
PRIMARY_BAR_MODE = "PRIMARY_XSTO_CLOB"


@dataclass(frozen=True)
class NasdaqInstrument:
    ticker: str
    isin: str
    company_name: str
    sector_group: str
    primary_mic: str = PRIMARY_MIC
    currency: str = PRIMARY_CURRENCY


# Research-universe mapping used only by the isolated Regime Trading project.
# Tickers match the existing Yahoo/database naming convention.
NASDAQ_INSTRUMENTS = [
    NasdaqInstrument("ALFA.ST", "SE0000695876", "Alfa Laval AB", "INDUSTRIALS"),
    NasdaqInstrument("ATCO-A.ST", "SE0017486889", "Atlas Copco AB A", "INDUSTRIALS"),
    NasdaqInstrument("ATCO-B.ST", "SE0017486897", "Atlas Copco AB B", "INDUSTRIALS"),
    NasdaqInstrument("AZN.ST", "GB0009895292", "AstraZeneca PLC", "HEALTH_CARE"),
    NasdaqInstrument("BOL.ST", "SE0020050417", "Boliden AB", "BASIC_MATERIALS"),
    NasdaqInstrument("ERIC-B.ST", "SE0000108656", "Ericsson B", "TECHNOLOGY"),
    NasdaqInstrument("EVO.ST", "SE0012673267", "Evolution AB", "CONSUMER_SERVICES"),
    NasdaqInstrument("SAND.ST", "SE0000667891", "Sandvik AB", "INDUSTRIALS"),
    NasdaqInstrument("SEB-A.ST", "SE0000148884", "SEB A", "BANKS"),
    NasdaqInstrument("SHB-A.ST", "SE0007100599", "Handelsbanken A", "BANKS"),
    NasdaqInstrument("SWED-A.ST", "SE0000242455", "Swedbank A", "BANKS"),
]

TICKER_BY_ISIN = {instrument.isin: instrument.ticker for instrument in NASDAQ_INSTRUMENTS}
INSTRUMENT_BY_TICKER = {
    instrument.ticker: instrument for instrument in NASDAQ_INSTRUMENTS
}
INSTRUMENT_BY_ISIN = {
    instrument.isin: instrument for instrument in NASDAQ_INSTRUMENTS
}


def ensure_nasdaq_directories() -> None:
    for directory in [
        NASDAQ_RAW_DIR,
        NASDAQ_PROBE_DIR,
        NASDAQ_INCOMING_DIR,
        NASDAQ_ARCHIVE_DIR,
    ]:
        Path(directory).mkdir(parents=True, exist_ok=True)
