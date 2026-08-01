from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_csv_for_power_bi(df: pd.DataFrame, output_file: Path) -> None:
    """Write a stable UTF-8 CSV suitable for Power BI imports."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )
