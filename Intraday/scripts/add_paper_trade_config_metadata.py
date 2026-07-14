import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_POSITION_SIZE,
)
from Intraday.core.paths import PAPER_TRADES


CAPITAL_MODEL = "FIXED_FRACTION_OF_INITIAL_CAPITAL"

METADATA_COLUMNS = [
    "initial_capital",
    "position_size_pct",
    "max_open_positions",
    "capital_model",
]


def is_blank(series: pd.Series) -> pd.Series:
    return (
        series.isna()
        | (series.astype(str).str.strip() == "")
        | (series.astype(str).str.lower().str.strip() == "nan")
    )


def add_metadata(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    defaults = {
        "initial_capital": float(ORB_INITIAL_CAPITAL),
        "position_size_pct": float(ORB_POSITION_SIZE),
        "max_open_positions": int(ORB_MAX_OPEN_POSITIONS),
        "capital_model": CAPITAL_MODEL,
    }

    for column, default_value in defaults.items():
        if column not in df.columns:
            df[column] = default_value
            continue

        blank_rows = is_blank(df[column])
        df.loc[blank_rows, column] = default_value

    df["initial_capital"] = pd.to_numeric(
        df["initial_capital"],
        errors="coerce",
    ).fillna(float(ORB_INITIAL_CAPITAL))

    df["position_size_pct"] = pd.to_numeric(
        df["position_size_pct"],
        errors="coerce",
    ).fillna(float(ORB_POSITION_SIZE))

    df["max_open_positions"] = pd.to_numeric(
        df["max_open_positions"],
        errors="coerce",
    ).fillna(int(ORB_MAX_OPEN_POSITIONS)).astype(int)

    df["capital_model"] = df["capital_model"].astype(str)

    return df


def main() -> None:
    print("\n=== ADD PAPER TRADE CONFIG METADATA ===")

    if not PAPER_TRADES.exists() or PAPER_TRADES.stat().st_size == 0:
        print(f"No paper trades file found or file is empty: {PAPER_TRADES}")
        return

    trades = pd.read_csv(PAPER_TRADES, dtype={"trade_id": str})

    before_columns = set(trades.columns)

    trades = add_metadata(trades)

    added_columns = [column for column in METADATA_COLUMNS if column not in before_columns]

    export_csv_for_power_bi(trades, PAPER_TRADES)

    expected_position_size = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)

    print(f"Rows updated: {len(trades)}")
    print(f"Initial capital: {float(ORB_INITIAL_CAPITAL):.2f}")
    print(f"Position size pct: {float(ORB_POSITION_SIZE):.4f}")
    print(f"Expected position size SEK: {expected_position_size:.2f}")
    print(f"Max open positions: {int(ORB_MAX_OPEN_POSITIONS)}")
    print(f"Capital model: {CAPITAL_MODEL}")

    if added_columns:
        print(f"Added columns: {added_columns}")
    else:
        print("Metadata columns already existed; blank values were filled only.")

    print(f"Saved -> {PAPER_TRADES}")


if __name__ == "__main__":
    main()