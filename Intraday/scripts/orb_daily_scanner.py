import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_MAX_OPENING_RANGE,
    ORB_MIN_GAP,
    ORB_R_MULTIPLE,
)
from Intraday.core.orb_strategy import load_intraday_prices
from Intraday.core.paths import ORB_SIGNAL_HISTORY, ORB_SIGNALS_LATEST


ALLOWED_TICKERS = ORB_ALLOWED_TICKERS
MAX_OPENING_RANGE = ORB_MAX_OPENING_RANGE
MIN_GAP = ORB_MIN_GAP
R_MULTIPLE = ORB_R_MULTIPLE

OPENING_RANGE_START = pd.to_datetime("09:00").time()
OPENING_RANGE_END = pd.to_datetime("09:30").time()

BREAKOUT_START = pd.to_datetime(ORB_BREAKOUT_START).time()
BREAKOUT_END = pd.to_datetime(ORB_BREAKOUT_END).time()

OUTPUT_COLUMNS = [
    "signal_key",
    "scan_date",
    "ticker",
    "status",
    "current_price",
    "entry_trigger",
    "stop_price",
    "target_price",
    "risk_pct",
    "target_return_pct",
    "gap",
    "opening_range_pct",
    "breakout_time",
    "breakout_price",
    "last_bar",
]


def normalise_intraday_data(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure datetime, date, and time fields are consistently available."""
    df = df.copy()

    if "datetime" not in df.columns:
        raise ValueError("Intraday price data must contain a 'datetime' column.")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).copy()

    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.time
    df["ticker"] = df["ticker"].astype(str).str.strip()

    return df


def add_scan_date(
    df: pd.DataFrame,
    require_complete: bool = False,
) -> pd.DataFrame:
    """
    Add or normalize the stable scanner snapshot key: scan_date.

    For legacy history rows, try scan_date first, then last_bar,
    breakout_time, and date.
    """
    df = df.copy()

    parsed_dates = pd.Series(
        pd.NaT,
        index=df.index,
        dtype="datetime64[ns]",
    )

    for source_column in ["scan_date", "last_bar", "breakout_time", "date"]:
        if source_column in df.columns:
            candidate_dates = pd.to_datetime(
                df[source_column],
                errors="coerce",
            )
            parsed_dates = parsed_dates.fillna(candidate_dates)

    df["scan_date"] = parsed_dates.dt.strftime("%Y-%m-%d")

    if require_complete and df["scan_date"].isna().any():
        bad_rows = df.loc[
            df["scan_date"].isna(),
            [column for column in ["ticker", "last_bar"] if column in df.columns],
        ]

        raise ValueError(
            "Could not determine scan_date for current scanner rows:\n"
            f"{bad_rows.to_string(index=False)}"
        )

    return df


def build_scanner_result(df: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    """Run the daily ORB scanner for the newest available trading day."""
    df = normalise_intraday_data(df)

    df = df[df["ticker"].isin(ALLOWED_TICKERS)].copy()

    if df.empty:
        raise ValueError(
            "No intraday data exists for the configured ORB ticker universe."
        )

    latest_date = df["date"].max()
    today = df[df["date"] == latest_date].copy()

    if today.empty:
        raise ValueError(f"No intraday rows found for latest date: {latest_date}")

    opening = today[
        (today["time"] >= OPENING_RANGE_START)
        & (today["time"] <= OPENING_RANGE_END)
    ].copy()

    if opening.empty:
        raise ValueError(
            f"No opening-range data found for {latest_date}. "
            "Expected bars from 09:00 through 09:30."
        )

    orb = (
        opening.sort_values("datetime")
        .groupby("ticker", as_index=False)
        .agg(
            opening_high=("high", "max"),
            opening_low=("low", "min"),
            day_open=("open", "first"),
        )
    )

    daily_open = (
        df.sort_values(["ticker", "datetime"])
        .groupby(["ticker", "date"], as_index=False)
        .agg(day_open=("open", "first"))
        .sort_values(["ticker", "date"])
    )

    daily_open["prev_open"] = (
        daily_open.groupby("ticker")["day_open"].shift(1)
    )

    latest_prev_open = daily_open.loc[
        daily_open["date"] == latest_date,
        ["ticker", "prev_open"],
    ]

    orb = orb.merge(latest_prev_open, on="ticker", how="left")

    # These are decimal values during strategy calculation:
    # 0.01 means 1%. They are converted to percentage points for output later.
    orb["gap"] = orb["day_open"] / orb["prev_open"] - 1
    orb["opening_range_pct"] = orb["opening_high"] / orb["opening_low"] - 1

    orb["entry_trigger"] = orb["opening_high"]
    orb["stop_price"] = orb["opening_low"]

    orb["risk"] = orb["entry_trigger"] - orb["stop_price"]
    orb["risk_pct"] = orb["risk"] / orb["entry_trigger"]

    orb["target_price"] = (
        orb["entry_trigger"] + R_MULTIPLE * orb["risk"]
    )
    orb["target_return_pct"] = (
        orb["target_price"] / orb["entry_trigger"] - 1
    )

    orb["valid_setup"] = (
        (orb["gap"] >= MIN_GAP)
        & (orb["opening_range_pct"] <= MAX_OPENING_RANGE)
        & (orb["risk"] > 0)
    ).fillna(False)

    latest_prices = (
        today.sort_values("datetime")
        .groupby("ticker", as_index=False)
        .tail(1)[["ticker", "close", "datetime"]]
        .rename(
            columns={
                "close": "current_price",
                "datetime": "last_bar",
            }
        )
    )

    orb = orb.merge(latest_prices, on="ticker", how="left")

    breakout_rows = []

    for _, row in orb.iterrows():
        ticker = row["ticker"]

        if not row["valid_setup"]:
            breakout_rows.append(
                {
                    "ticker": ticker,
                    "breakout_time": pd.NaT,
                    "breakout_price": None,
                    "status": "INVALID",
                }
            )
            continue

        ticker_today = (
            today[today["ticker"] == ticker]
            .sort_values("datetime")
            .copy()
        )

        trade_window = ticker_today[
            (ticker_today["time"] >= BREAKOUT_START)
            & (ticker_today["time"] <= BREAKOUT_END)
        ]

        breakout = trade_window[
            trade_window["high"] > row["entry_trigger"]
        ]

        if breakout.empty:
            breakout_rows.append(
                {
                    "ticker": ticker,
                    "breakout_time": pd.NaT,
                    "breakout_price": None,
                    "status": "NOT_TRIGGERED",
                }
            )
        else:
            first_breakout = breakout.iloc[0]

            breakout_rows.append(
                {
                    "ticker": ticker,
                    "breakout_time": first_breakout["datetime"],
                    "breakout_price": first_breakout["close"],
                    "status": "TRIGGERED",
                }
            )

    breakouts = pd.DataFrame(breakout_rows)

    result = orb.merge(breakouts, on="ticker", how="left")

    result = result[
        [
            "ticker",
            "status",
            "current_price",
            "entry_trigger",
            "stop_price",
            "target_price",
            "risk_pct",
            "target_return_pct",
            "gap",
            "opening_range_pct",
            "breakout_time",
            "breakout_price",
            "last_bar",
        ]
    ].sort_values(["status", "ticker"]).copy()

    # Convert decimals into percentage points for the Power BI output.
    # Example: 0.0058 becomes 0.58, which means 0.58%.
    percentage_columns = [
        "risk_pct",
        "target_return_pct",
        "gap",
        "opening_range_pct",
    ]

    for column in percentage_columns:
        result[column] = (
            pd.to_numeric(result[column], errors="coerce") * 100
        ).round(2)

    result["scan_date"] = pd.Timestamp(latest_date).strftime("%Y-%m-%d")

    # Stable technical key for Power BI compatibility and traceability.
    # The actual history deduplication still uses scan_date + ticker.
    result["signal_key"] = (
        result["scan_date"].astype(str)
        + "_"
        + result["ticker"].astype(str)
    )

    result = result[OUTPUT_COLUMNS].copy()

    return result, latest_date


def update_signal_history(latest_signals: pd.DataFrame) -> pd.DataFrame:
    """
    Save exactly one scanner result per ticker and scan date.

    Running the scanner repeatedly for the same market day replaces that
    day's rows instead of creating duplicate historical records.
    """
    current = add_scan_date(latest_signals, require_complete=True)

    current["ticker"] = current["ticker"].astype(str).str.strip()

    current = current.drop_duplicates(
        subset=["scan_date", "ticker"],
        keep="last",
    ).copy()

    if ORB_SIGNAL_HISTORY.exists():
        history = pd.read_csv(ORB_SIGNAL_HISTORY)
        history = add_scan_date(history, require_complete=False)

        if "ticker" not in history.columns:
            raise ValueError(
                "Existing orb_signal_history.csv does not contain a ticker column."
            )

        history = history[history["ticker"].notna()].copy()
        history["ticker"] = history["ticker"].astype(str).str.strip()

        # Remove malformed legacy rows that cannot be assigned to a scan date.
        history = history[
            history["scan_date"].notna()
            & history["ticker"].ne("")
            & history["ticker"].ne("nan")
        ].copy()
    else:
        history = pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Keep a clean, stable schema and remove old fields such as signal_key.
    for column in OUTPUT_COLUMNS:
        if column not in history.columns:
            history[column] = pd.NA

    history = history[OUTPUT_COLUMNS].copy()
    current = current[OUTPUT_COLUMNS].copy()

    # Ensure both legacy and new history rows use the same stable key format.
    history["signal_key"] = (
        history["scan_date"].astype(str)
        + "_"
        + history["ticker"].astype(str)
    )

    current["signal_key"] = (
        current["scan_date"].astype(str)
        + "_"
        + current["ticker"].astype(str)
    )

    current_scan_dates = current["scan_date"].dropna().unique().tolist()

    # Replace every previous scanner snapshot for the current market date.
    history = history[
        ~history["scan_date"].isin(current_scan_dates)
    ].copy()

    updated_history = pd.concat(
        [history, current],
        ignore_index=True,
    )

    # Clean any duplicate legacy records too.
    updated_history = updated_history.drop_duplicates(
        subset=["scan_date", "ticker"],
        keep="last",
    )

    updated_history = updated_history.sort_values(
        ["scan_date", "ticker"],
        kind="stable",
    ).reset_index(drop=True)

    export_csv_for_power_bi(updated_history, ORB_SIGNAL_HISTORY)

    return updated_history


def main() -> None:
    print("\n=== ORB DAILY SCANNER ===")

    intraday_prices = load_intraday_prices()

    result, latest_date = build_scanner_result(intraday_prices)

    export_csv_for_power_bi(result, ORB_SIGNALS_LATEST)

    history = update_signal_history(result)

    unique_history_rows = len(
        history[["scan_date", "ticker"]].drop_duplicates()
    )

    print(f"Date: {latest_date}")
    print(result.to_string(index=False))

    print(f"\nSaved latest signals -> {ORB_SIGNALS_LATEST}")
    print(f"Updated history -> {ORB_SIGNAL_HISTORY}")
    print(
        f"History rows: {len(history)} | "
        f"Unique scan-date/ticker rows: {unique_history_rows}"
    )


if __name__ == "__main__":
    main()