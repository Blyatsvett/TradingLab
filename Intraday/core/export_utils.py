from pathlib import Path
import pandas as pd


DATETIME_COLUMNS = {
    "date",
    "entry_time",
    "exit_time",
    "created_at",
    "breakout_time",
    "last_bar",
}


def clean_for_power_bi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in df.columns:
        if col in DATETIME_COLUMNS:
            converted = pd.to_datetime(df[col], errors="coerce")

            if col == "date":
                df[col] = converted.dt.strftime("%Y-%m-%d").fillna("")
            else:
                df[col] = converted.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].fillna(0)
        else:
            df[col] = df[col].fillna("")

    return df


def export_csv_for_power_bi(
    df: pd.DataFrame,
    path: Path,
    columns: list[str] | None = None,
) -> None:
    df = df.copy()

    if columns is not None:
        for col in columns:
            if col not in df.columns:
                df[col] = 0

        df = df[columns]

    df = clean_for_power_bi(df)

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")