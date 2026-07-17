from __future__ import annotations

from pathlib import Path

import pandas as pd

from Intraday.core.orb_config import ORB_INITIAL_CAPITAL, ORB_POSITION_SIZE
from Intraday.core.paths import DATA_DIR


LAB_TRADES_FILE = DATA_DIR / "intraday_strategy_lab_trades.csv"
SHADOW_TRADES_FILE = DATA_DIR / "orb_position_sizing_shadow_trades.csv"

OUTPUT_SUMMARY_FILE = DATA_DIR / "strategy_lab_orb_baseline_comparison_summary.csv"
OUTPUT_MISMATCH_FILE = DATA_DIR / "strategy_lab_orb_baseline_comparison_mismatches.csv"

LAB_ORB_STRATEGY_NAME = "01_ORB_BREAKOUT_BASELINE"
SHADOW_BASELINE_METHOD = "baseline_fixed_10pct"

TOLERANCE = 1e-6


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    return pd.read_csv(path)


def normalise_date(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return ""

    return parsed.strftime("%Y-%m-%d")


def normalise_datetime(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return ""

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def prepare_trades(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    output = df.copy()

    required_columns = ["date", "ticker", "entry_time"]

    missing = [col for col in required_columns if col not in output.columns]

    if missing:
        raise ValueError(f"{source_name} missing required columns: {missing}")

    output["date_norm"] = output["date"].apply(normalise_date)
    output["entry_time_norm"] = output["entry_time"].apply(normalise_datetime)

    if "exit_time" in output.columns:
        output["exit_time_norm"] = output["exit_time"].apply(normalise_datetime)
    else:
        output["exit_time_norm"] = ""

    output["ticker_norm"] = output["ticker"].astype(str).str.strip()

    output["comparison_key"] = (
        output["date_norm"]
        + "|"
        + output["ticker_norm"]
        + "|"
        + output["entry_time_norm"]
    )

    if output["comparison_key"].duplicated().any():
        duplicates = output[output["comparison_key"].duplicated(keep=False)].copy()
        duplicate_keys = sorted(duplicates["comparison_key"].unique())

        raise ValueError(
            f"{source_name} has duplicated comparison keys. "
            f"Example duplicates: {duplicate_keys[:10]}"
        )

    return output


def numeric_value(row: pd.Series, col: str) -> float:
    return float(pd.to_numeric(row.get(col, 0.0), errors="coerce"))


def compare_numeric_column(
    merged: pd.DataFrame,
    col: str,
    mismatches: list[dict],
) -> None:
    lab_col = f"{col}_lab"
    shadow_col = f"{col}_shadow"

    if lab_col not in merged.columns or shadow_col not in merged.columns:
        return

    lab_values = pd.to_numeric(merged[lab_col], errors="coerce").fillna(0.0)
    shadow_values = pd.to_numeric(merged[shadow_col], errors="coerce").fillna(0.0)

    diffs = lab_values - shadow_values

    bad = merged[diffs.abs() > TOLERANCE].copy()

    for idx, row in bad.iterrows():
        mismatches.append(
            {
                "comparison_key": row["comparison_key"],
                "field": col,
                "lab_value": lab_values.loc[idx],
                "shadow_value": shadow_values.loc[idx],
                "difference": diffs.loc[idx],
            }
        )


def compare_text_column(
    merged: pd.DataFrame,
    col: str,
    mismatches: list[dict],
) -> None:
    lab_col = f"{col}_lab"
    shadow_col = f"{col}_shadow"

    if lab_col not in merged.columns or shadow_col not in merged.columns:
        return

    lab_values = merged[lab_col].fillna("").astype(str).str.lower().str.strip()
    shadow_values = merged[shadow_col].fillna("").astype(str).str.lower().str.strip()

    bad = merged[lab_values != shadow_values].copy()

    for idx, row in bad.iterrows():
        mismatches.append(
            {
                "comparison_key": row["comparison_key"],
                "field": col,
                "lab_value": lab_values.loc[idx],
                "shadow_value": shadow_values.loc[idx],
                "difference": "",
            }
        )


def main() -> None:
    print("\n=== COMPARE STRATEGY LAB ORB BASELINE ===")
    print("Compares Strategy Lab ORB baseline against existing shadow baseline.")
    print(f"Lab file    : {LAB_TRADES_FILE}")
    print(f"Shadow file : {SHADOW_TRADES_FILE}")

    lab = load_csv(LAB_TRADES_FILE)
    shadow = load_csv(SHADOW_TRADES_FILE)

    if "strategy_name" not in lab.columns:
        raise ValueError("Strategy Lab trades file missing strategy_name column.")

    if "shadow_method" not in shadow.columns:
        raise ValueError("Shadow trades file missing shadow_method column.")

    lab_orb = lab[lab["strategy_name"].eq(LAB_ORB_STRATEGY_NAME)].copy()
    shadow_baseline = shadow[
        shadow["shadow_method"].eq(SHADOW_BASELINE_METHOD)
    ].copy()

    lab_orb = prepare_trades(lab_orb, "Strategy Lab ORB baseline")
    shadow_baseline = prepare_trades(shadow_baseline, "Shadow baseline")

    lab_keys = set(lab_orb["comparison_key"])
    shadow_keys = set(shadow_baseline["comparison_key"])

    missing_from_lab = sorted(shadow_keys - lab_keys)
    missing_from_shadow = sorted(lab_keys - shadow_keys)
    matching_keys = sorted(lab_keys.intersection(shadow_keys))

    merged = lab_orb.merge(
        shadow_baseline,
        on="comparison_key",
        how="inner",
        suffixes=("_lab", "_shadow"),
    )

    mismatches = []

    numeric_columns_to_compare = [
        "entry_price",
        "stop_price",
        "target_price",
        "exit_price",
        "gross_return",
        "net_return",
        "risk_pct",
        "target_return_pct",
        "r_multiple_achieved",
    ]

    text_columns_to_compare = [
        "exit_reason",
        "exit_time_norm",
    ]

    for col in numeric_columns_to_compare:
        compare_numeric_column(merged, col, mismatches)

    for col in text_columns_to_compare:
        compare_text_column(merged, col, mismatches)

    lab_total_account_return = (
        pd.to_numeric(lab_orb["net_return"], errors="coerce").fillna(0.0).sum()
        * ORB_POSITION_SIZE
    )

    shadow_total_account_return = (
        pd.to_numeric(shadow_baseline["net_return"], errors="coerce").fillna(0.0).sum()
        * ORB_POSITION_SIZE
    )

    lab_total_pnl = lab_total_account_return * ORB_INITIAL_CAPITAL
    shadow_total_pnl = shadow_total_account_return * ORB_INITIAL_CAPITAL

    status = "PASS"

    if missing_from_lab or missing_from_shadow or mismatches:
        status = "FAIL"

    summary = pd.DataFrame(
        [
            {
                "status": status,
                "lab_strategy_name": LAB_ORB_STRATEGY_NAME,
                "shadow_method": SHADOW_BASELINE_METHOD,
                "lab_trades": len(lab_orb),
                "shadow_trades": len(shadow_baseline),
                "matching_trades": len(matching_keys),
                "missing_from_lab": len(missing_from_lab),
                "missing_from_shadow": len(missing_from_shadow),
                "mismatched_fields": len(mismatches),
                "lab_total_account_return": lab_total_account_return,
                "shadow_total_account_return": shadow_total_account_return,
                "return_difference": (
                    lab_total_account_return - shadow_total_account_return
                ),
                "lab_total_pnl_sek": lab_total_pnl,
                "shadow_total_pnl_sek": shadow_total_pnl,
                "pnl_difference_sek": lab_total_pnl - shadow_total_pnl,
            }
        ]
    )

    mismatch_rows = []

    for key in missing_from_lab:
        mismatch_rows.append(
            {
                "comparison_key": key,
                "field": "missing_trade",
                "lab_value": "MISSING",
                "shadow_value": "PRESENT",
                "difference": "",
            }
        )

    for key in missing_from_shadow:
        mismatch_rows.append(
            {
                "comparison_key": key,
                "field": "missing_trade",
                "lab_value": "PRESENT",
                "shadow_value": "MISSING",
                "difference": "",
            }
        )

    mismatch_rows.extend(mismatches)

    mismatch_columns = [
        "comparison_key",
        "field",
        "lab_value",
        "shadow_value",
        "difference",
    ]

    mismatch_df = pd.DataFrame(mismatch_rows, columns=mismatch_columns)

    summary.to_csv(OUTPUT_SUMMARY_FILE, index=False, encoding="utf-8")
    mismatch_df.to_csv(OUTPUT_MISMATCH_FILE, index=False, encoding="utf-8")

    print("\n=== COMPARISON SUMMARY ===")
    print(summary.to_string(index=False))

    if mismatch_df.empty:
        print("\nNo mismatches found.")
    else:
        print("\n=== MISMATCHES ===")
        print(mismatch_df.head(50).to_string(index=False))
        print(f"\nTotal mismatch rows: {len(mismatch_df)}")

    print(f"\nSaved summary   -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved mismatches -> {OUTPUT_MISMATCH_FILE}")

    if status == "PASS":
        print("\nPASS: Strategy Lab ORB baseline matches existing shadow baseline.")
    else:
        print("\nFAIL: Strategy Lab ORB baseline does not match existing shadow baseline.")


if __name__ == "__main__":
    main()