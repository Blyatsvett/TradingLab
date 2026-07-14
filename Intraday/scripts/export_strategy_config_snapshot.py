from datetime import datetime

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPENING_RANGE,
    ORB_MAX_OPEN_POSITIONS,
    ORB_MIN_GAP,
    ORB_POSITION_SIZE,
    ORB_R_MULTIPLE,
    ORB_STRATEGY_VERSION,
)
from Intraday.core.paths import DATA_DIR


OUTPUT_PATH = DATA_DIR / "strategy_config_snapshot.csv"

CAPITAL_MODEL = "FIXED_FRACTION_OF_INITIAL_CAPITAL"
POSITION_RULE = "MAX_CONCURRENT_OPEN_POSITIONS"


def pct_display(value: float) -> str:
    return f"{float(value) * 100:.2f}%"


def currency_display(value: float) -> str:
    return f"{float(value):,.2f} SEK"


def make_row(
    display_order: int,
    setting_key: str,
    setting_label: str,
    value,
    value_numeric,
    value_type: str,
    display_value: str,
    description: str,
    exported_at: str,
) -> dict:
    return {
        "exported_at": exported_at,
        "strategy_version": ORB_STRATEGY_VERSION,
        "display_order": display_order,
        "setting_key": setting_key,
        "setting_label": setting_label,
        "value": str(value),
        "value_numeric": value_numeric,
        "value_type": value_type,
        "display_value": display_value,
        "description": description,
    }


def build_config_snapshot() -> pd.DataFrame:
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    allowed_tickers_text = ", ".join(ORB_ALLOWED_TICKERS)
    position_size_sek = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)

    rows = [
        make_row(
            1,
            "ORB_STRATEGY_VERSION",
            "Strategy Version",
            ORB_STRATEGY_VERSION,
            None,
            "text",
            ORB_STRATEGY_VERSION,
            "Current live/paper ORB strategy identifier.",
            exported_at,
        ),
        make_row(
            2,
            "ORB_ALLOWED_TICKERS",
            "Allowed Tickers",
            allowed_tickers_text,
            None,
            "text",
            allowed_tickers_text,
            "Ticker basket used by the live scanner.",
            exported_at,
        ),
        make_row(
            3,
            "ORB_ALLOWED_TICKER_COUNT",
            "Ticker Count",
            len(ORB_ALLOWED_TICKERS),
            len(ORB_ALLOWED_TICKERS),
            "integer",
            str(len(ORB_ALLOWED_TICKERS)),
            "Number of tickers in the live scanner basket.",
            exported_at,
        ),
        make_row(
            4,
            "ORB_MAX_OPEN_POSITIONS",
            "Max Open Positions",
            ORB_MAX_OPEN_POSITIONS,
            ORB_MAX_OPEN_POSITIONS,
            "integer",
            str(ORB_MAX_OPEN_POSITIONS),
            "Maximum number of concurrent open paper positions.",
            exported_at,
        ),
        make_row(
            5,
            "POSITION_RULE",
            "Position Rule",
            POSITION_RULE,
            None,
            "text",
            POSITION_RULE,
            "How the live paper engine limits trade creation.",
            exported_at,
        ),
        make_row(
            6,
            "ORB_BREAKOUT_START",
            "Breakout Start",
            ORB_BREAKOUT_START,
            None,
            "time",
            ORB_BREAKOUT_START,
            "Earliest allowed breakout time.",
            exported_at,
        ),
        make_row(
            7,
            "ORB_BREAKOUT_END",
            "Breakout End",
            ORB_BREAKOUT_END,
            None,
            "time",
            ORB_BREAKOUT_END,
            "Latest allowed breakout time.",
            exported_at,
        ),
        make_row(
            8,
            "ORB_R_MULTIPLE",
            "Target R Multiple",
            ORB_R_MULTIPLE,
            ORB_R_MULTIPLE,
            "decimal",
            f"{float(ORB_R_MULTIPLE):.2f}R",
            "Target distance relative to opening-range risk.",
            exported_at,
        ),
        make_row(
            9,
            "ORB_MAX_OPENING_RANGE",
            "Max Opening Range",
            ORB_MAX_OPENING_RANGE,
            ORB_MAX_OPENING_RANGE,
            "percentage_decimal",
            pct_display(ORB_MAX_OPENING_RANGE),
            "Maximum allowed opening range as decimal fraction.",
            exported_at,
        ),
        make_row(
            10,
            "ORB_MIN_GAP",
            "Minimum Gap",
            ORB_MIN_GAP,
            ORB_MIN_GAP,
            "percentage_decimal",
            pct_display(ORB_MIN_GAP),
            "Minimum required gap as decimal fraction.",
            exported_at,
        ),
        make_row(
            11,
            "ORB_COST_PER_TRADE",
            "Cost Per Trade",
            ORB_COST_PER_TRADE,
            ORB_COST_PER_TRADE,
            "percentage_decimal",
            pct_display(ORB_COST_PER_TRADE),
            "Estimated trading cost per trade as decimal fraction.",
            exported_at,
        ),
        make_row(
            12,
            "ORB_INITIAL_CAPITAL",
            "Initial Capital",
            ORB_INITIAL_CAPITAL,
            ORB_INITIAL_CAPITAL,
            "currency",
            currency_display(ORB_INITIAL_CAPITAL),
            "Paper account starting capital.",
            exported_at,
        ),
        make_row(
            13,
            "ORB_POSITION_SIZE",
            "Position Size %",
            ORB_POSITION_SIZE,
            ORB_POSITION_SIZE,
            "percentage_decimal",
            pct_display(ORB_POSITION_SIZE),
            "Fraction of initial capital used per paper trade.",
            exported_at,
        ),
        make_row(
            14,
            "PAPER_POSITION_SIZE_SEK",
            "Position Size SEK",
            position_size_sek,
            position_size_sek,
            "currency",
            currency_display(position_size_sek),
            "Current paper position size in SEK.",
            exported_at,
        ),
        make_row(
            15,
            "CAPITAL_MODEL",
            "Capital Model",
            CAPITAL_MODEL,
            None,
            "text",
            CAPITAL_MODEL,
            "Capital sizing model used by the paper engine.",
            exported_at,
        ),
    ]

    return pd.DataFrame(rows)


def main() -> None:
    print("\n=== EXPORT STRATEGY CONFIG SNAPSHOT ===")

    snapshot = build_config_snapshot()

    export_csv_for_power_bi(
        snapshot,
        OUTPUT_PATH,
        columns=[
            "exported_at",
            "strategy_version",
            "display_order",
            "setting_key",
            "setting_label",
            "value",
            "value_numeric",
            "value_type",
            "display_value",
            "description",
        ],
    )

    print(f"Rows exported: {len(snapshot)}")
    print(f"Strategy version: {ORB_STRATEGY_VERSION}")
    print(f"Ticker basket: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Position size: {float(ORB_POSITION_SIZE) * 100:.2f}%")
    print(f"Saved -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()