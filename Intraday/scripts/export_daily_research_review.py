from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.paths import (
    DATA_DIR,
    ORB_SIGNALS_LATEST,
    PAPER_TRADES,
)


PAPER_ACCOUNT_EQUITY_CURVE = DATA_DIR / "paper_account_equity_curve.csv"
WORKFLOW_RUN_AUDIT = DATA_DIR / "workflow_run_audit.csv"

STRATEGY_LAB_SHADOW_STATUS = DATA_DIR / "strategy_lab_shadow_status.csv"
STRATEGY_LAB_SHADOW_SUMMARY = DATA_DIR / "strategy_lab_shadow_summary.csv"
STRATEGY_LAB_SHADOW_LATEST_TRADES = DATA_DIR / "strategy_lab_shadow_latest_trades.csv"

OUTPUT_REVIEW_SUMMARY = DATA_DIR / "daily_research_review_summary.csv"
OUTPUT_REVIEW_ITEMS = DATA_DIR / "daily_research_review_items.csv"
OUTPUT_REVIEW_ORB_SIGNALS = DATA_DIR / "daily_research_review_orb_signals.csv"
OUTPUT_REVIEW_PAPER_TRADES_TODAY = DATA_DIR / "daily_research_review_paper_trades_today.csv"
OUTPUT_REVIEW_SHADOW_TRADES_TODAY = DATA_DIR / "daily_research_review_shadow_trades_today.csv"
OUTPUT_REVIEW_TEXT = DATA_DIR / "daily_research_review_latest.txt"


SUMMARY_COLUMNS = [
    "generated_at",
    "review_date",
    "orb_signal_rows",
    "orb_triggered_signals",
    "orb_not_triggered_signals",
    "orb_invalid_signals",
    "paper_total_trades",
    "paper_open_trades",
    "paper_closed_trades",
    "paper_opened_today",
    "paper_closed_today",
    "paper_realized_pnl_today",
    "paper_final_account_equity",
    "shadow_strategy_count",
    "shadow_ready_count",
    "shadow_latest_trade_count",
    "shadow_active_shadow_latest_trades",
    "shadow_watchlist_latest_trades",
    "shadow_diagnostic_latest_trades",
    "shadow_production_reference_latest_trades",
    "latest_audit_validation_status",
    "latest_audit_timestamp",
    "operating_status",
]

ITEM_COLUMNS = [
    "generated_at",
    "review_date",
    "section",
    "item",
    "status",
    "value",
    "details",
]


def read_required_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    return pd.read_csv(path)


def read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def date_string(value) -> str:
    converted = pd.to_datetime(value, errors="coerce")

    if pd.isna(converted):
        return ""

    return converted.strftime("%Y-%m-%d")


def datetime_string(value) -> str:
    converted = pd.to_datetime(value, errors="coerce")

    if pd.isna(converted):
        return ""

    return converted.strftime("%Y-%m-%d %H:%M:%S")


def normalise_date_column(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()

    if output.empty:
        return output

    if "date" in output.columns:
        output["date"] = pd.to_datetime(
            output["date"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
        return output

    if "scan_date" in output.columns:
        output["date"] = pd.to_datetime(
            output["scan_date"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
        return output

    if "entry_time" in output.columns:
        output["date"] = pd.to_datetime(
            output["entry_time"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
        return output

    return output


def latest_date_from_sources(
    signals: pd.DataFrame,
    paper_trades: pd.DataFrame,
    shadow_status: pd.DataFrame,
    shadow_latest_trades: pd.DataFrame,
) -> str:
    candidate_dates = []

    if not shadow_status.empty and "latest_data_date" in shadow_status.columns:
        candidate_dates.extend(
            shadow_status["latest_data_date"].dropna().astype(str).tolist()
        )

    if not shadow_latest_trades.empty and "date" in shadow_latest_trades.columns:
        candidate_dates.extend(
            shadow_latest_trades["date"].dropna().astype(str).tolist()
        )

    if not signals.empty and "scan_date" in signals.columns:
        candidate_dates.extend(
            signals["scan_date"].dropna().astype(str).tolist()
        )

    if not paper_trades.empty:
        temp = normalise_date_column(paper_trades)
        if "date" in temp.columns:
            candidate_dates.extend(temp["date"].dropna().astype(str).tolist())

    converted = pd.to_datetime(candidate_dates, errors="coerce")
    converted = converted[~pd.isna(converted)]

    if len(converted) == 0:
        return datetime.now().strftime("%Y-%m-%d")

    return pd.Series(converted).max().strftime("%Y-%m-%d")


def parse_bool_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes"])
    )


def count_signal_statuses(signals: pd.DataFrame) -> dict:
    if signals.empty or "status" not in signals.columns:
        return {
            "triggered": 0,
            "not_triggered": 0,
            "invalid": 0,
        }

    statuses = signals["status"].dropna().astype(str).str.upper()

    return {
        "triggered": int(statuses.eq("TRIGGERED").sum()),
        "not_triggered": int(statuses.eq("NOT_TRIGGERED").sum()),
        "invalid": int(statuses.eq("INVALID").sum()),
    }


def filter_paper_trades_today(
    paper_trades: pd.DataFrame,
    review_date: str,
) -> tuple[pd.DataFrame, int, int, float]:
    if paper_trades.empty:
        return paper_trades.copy(), 0, 0, 0.0

    output = paper_trades.copy()

    if "date" in output.columns:
        output["_opened_date"] = pd.to_datetime(
            output["date"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
    elif "entry_time" in output.columns:
        output["_opened_date"] = pd.to_datetime(
            output["entry_time"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
    else:
        output["_opened_date"] = ""

    if "exit_time" in output.columns:
        output["_closed_date"] = pd.to_datetime(
            output["exit_time"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
    else:
        output["_closed_date"] = ""

    opened_today_mask = output["_opened_date"].eq(review_date)
    closed_today_mask = output["_closed_date"].eq(review_date)

    status_closed = (
        output["status"].astype(str).str.upper().eq("CLOSED")
        if "status" in output.columns
        else pd.Series(False, index=output.index)
    )

    today = output[opened_today_mask | closed_today_mask].copy()

    opened_today = int(opened_today_mask.sum())
    closed_today = int((closed_today_mask & status_closed).sum())

    if "pnl_sek" in output.columns:
        pnl_today = float(
            pd.to_numeric(
                output.loc[closed_today_mask & status_closed, "pnl_sek"],
                errors="coerce",
            ).fillna(0.0).sum()
        )
    else:
        pnl_today = 0.0

    helper_columns = ["_opened_date", "_closed_date"]
    today = today.drop(columns=[col for col in helper_columns if col in today.columns])

    return today, opened_today, closed_today, pnl_today


def filter_shadow_trades_today(
    shadow_latest_trades: pd.DataFrame,
    review_date: str,
) -> pd.DataFrame:
    if shadow_latest_trades.empty:
        return shadow_latest_trades.copy()

    output = normalise_date_column(shadow_latest_trades)

    if "date" not in output.columns:
        return output.copy()

    return output[output["date"].eq(review_date)].copy()


def get_final_account_equity(account_curve: pd.DataFrame) -> float:
    if account_curve.empty:
        return 0.0

    if "account_trade_number" in account_curve.columns:
        account_curve = account_curve.copy()
        account_curve["account_trade_number"] = pd.to_numeric(
            account_curve["account_trade_number"],
            errors="coerce",
        )
        account_curve = account_curve.sort_values("account_trade_number")

    if "account_equity" not in account_curve.columns:
        return 0.0

    value = pd.to_numeric(
        account_curve["account_equity"],
        errors="coerce",
    ).dropna()

    if value.empty:
        return 0.0

    return float(value.iloc[-1])


def get_latest_audit_status(audit: pd.DataFrame) -> tuple[str, str]:
    if audit.empty:
        return "", ""

    if "run_timestamp" in audit.columns:
        temp = audit.copy()
        temp["_run_timestamp"] = pd.to_datetime(
            temp["run_timestamp"],
            errors="coerce",
        )
        temp = temp.sort_values("_run_timestamp")
    else:
        temp = audit.copy()

    latest = temp.tail(1)

    if latest.empty:
        return "", ""

    status = (
        str(latest["validation_status"].iloc[0])
        if "validation_status" in latest.columns
        else ""
    )

    timestamp = (
        datetime_string(latest["run_timestamp"].iloc[0])
        if "run_timestamp" in latest.columns
        else ""
    )

    return status, timestamp


def add_item(
    rows: list[dict],
    generated_at: str,
    review_date: str,
    section: str,
    item: str,
    status: str,
    value,
    details: str,
) -> None:
    rows.append(
        {
            "generated_at": generated_at,
            "review_date": review_date,
            "section": section,
            "item": item,
            "status": status,
            "value": value,
            "details": details,
        }
    )


def build_review_text(
    summary: dict,
    items: pd.DataFrame,
    shadow_today: pd.DataFrame,
    paper_today: pd.DataFrame,
) -> str:
    lines = []

    lines.append("DAILY RESEARCH REVIEW")
    lines.append("=====================")
    lines.append(f"Generated at: {summary['generated_at']}")
    lines.append(f"Review date : {summary['review_date']}")
    lines.append("")

    lines.append("PRODUCTION ORB")
    lines.append("--------------")
    lines.append(f"ORB signal rows      : {summary['orb_signal_rows']}")
    lines.append(f"Triggered signals    : {summary['orb_triggered_signals']}")
    lines.append(f"Not triggered signals: {summary['orb_not_triggered_signals']}")
    lines.append(f"Invalid signals      : {summary['orb_invalid_signals']}")
    lines.append(f"Paper total trades   : {summary['paper_total_trades']}")
    lines.append(f"Paper open trades    : {summary['paper_open_trades']}")
    lines.append(f"Paper closed trades  : {summary['paper_closed_trades']}")
    lines.append(f"Opened today         : {summary['paper_opened_today']}")
    lines.append(f"Closed today         : {summary['paper_closed_today']}")
    lines.append(f"Realized PnL today   : {summary['paper_realized_pnl_today']:.2f} SEK")
    lines.append(f"Final account equity : {summary['paper_final_account_equity']:.2f} SEK")
    lines.append("")

    lines.append("STRATEGY LAB SHADOW")
    lines.append("-------------------")
    lines.append(f"Shadow strategies ready : {summary['shadow_ready_count']} / {summary['shadow_strategy_count']}")
    lines.append(f"Shadow latest trades    : {summary['shadow_latest_trade_count']}")
    lines.append(f"Active shadow trades    : {summary['shadow_active_shadow_latest_trades']}")
    lines.append(f"Watchlist trades        : {summary['shadow_watchlist_latest_trades']}")
    lines.append(f"Diagnostic trades       : {summary['shadow_diagnostic_latest_trades']}")
    lines.append(f"Production ref trades   : {summary['shadow_production_reference_latest_trades']}")
    lines.append("")

    lines.append("AUDIT")
    lines.append("-----")
    lines.append(f"Latest audit validation status: {summary['latest_audit_validation_status']}")
    lines.append(f"Latest audit timestamp        : {summary['latest_audit_timestamp']}")
    lines.append(f"Operating status              : {summary['operating_status']}")
    lines.append("")

    lines.append("TODAY'S PAPER TRADES")
    lines.append("--------------------")
    if paper_today.empty:
        lines.append("No paper trades opened or closed on the review date.")
    else:
        display_cols = [
            col for col in [
                "trade_id",
                "date",
                "ticker",
                "status",
                "entry_time",
                "exit_time",
                "pnl_sek",
                "strategy_version",
            ]
            if col in paper_today.columns
        ]
        lines.append(paper_today[display_cols].to_string(index=False))

    lines.append("")
    lines.append("TODAY'S SHADOW TRADES")
    lines.append("---------------------")
    if shadow_today.empty:
        lines.append("No Strategy Lab shadow trades on the review date.")
    else:
        display_cols = [
            col for col in [
                "research_tier",
                "shadow_strategy_id",
                "strategy_name",
                "ticker",
                "date",
                "entry_time",
                "exit_reason",
                "account_return",
                "pnl_sek",
            ]
            if col in shadow_today.columns
        ]
        lines.append(shadow_today[display_cols].to_string(index=False))

    lines.append("")
    lines.append("OPERATING REMINDER")
    lines.append("------------------")
    lines.append("Trade/simulate only frozen ORB production.")
    lines.append("Strategy Lab shadow strategies are research-only.")
    lines.append("Do not promote strategies or change rules during market hours.")

    if not items.empty:
        warnings = items[items["status"].astype(str).str.upper().eq("WARN")]
        if not warnings.empty:
            lines.append("")
            lines.append("WARNINGS")
            lines.append("--------")
            for _, row in warnings.iterrows():
                lines.append(f"{row['section']} - {row['item']}: {row['details']}")

    return "\n".join(lines) + "\n"


def main() -> None:
    print("\n=== DAILY RESEARCH REVIEW ===")
    print("Builds one-day production + Strategy Lab shadow review.")
    print("Research-only shadow strategies remain separate from ORB production.")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    signals = read_required_csv(ORB_SIGNALS_LATEST)
    paper_trades = read_required_csv(PAPER_TRADES)
    account_curve = read_optional_csv(PAPER_ACCOUNT_EQUITY_CURVE)
    audit = read_optional_csv(WORKFLOW_RUN_AUDIT)

    shadow_status = read_required_csv(STRATEGY_LAB_SHADOW_STATUS)
    shadow_summary = read_required_csv(STRATEGY_LAB_SHADOW_SUMMARY)
    shadow_latest_trades = read_optional_csv(STRATEGY_LAB_SHADOW_LATEST_TRADES)

    signals = normalise_date_column(signals)
    paper_trades = normalise_date_column(paper_trades)
    shadow_latest_trades = normalise_date_column(shadow_latest_trades)

    review_date = latest_date_from_sources(
        signals=signals,
        paper_trades=paper_trades,
        shadow_status=shadow_status,
        shadow_latest_trades=shadow_latest_trades,
    )

    signal_counts = count_signal_statuses(signals)

    paper_today, paper_opened_today, paper_closed_today, paper_pnl_today = (
        filter_paper_trades_today(
            paper_trades=paper_trades,
            review_date=review_date,
        )
    )

    shadow_today = filter_shadow_trades_today(
        shadow_latest_trades=shadow_latest_trades,
        review_date=review_date,
    )

    if "status" in paper_trades.columns:
        paper_statuses = paper_trades["status"].astype(str).str.upper()
        paper_open_trades = int(paper_statuses.eq("OPEN").sum())
        paper_closed_trades = int(paper_statuses.eq("CLOSED").sum())
    else:
        paper_open_trades = 0
        paper_closed_trades = 0

    if "ready_for_monday" in shadow_status.columns:
        shadow_ready_count = int(parse_bool_series(shadow_status["ready_for_monday"]).sum())
    else:
        shadow_ready_count = 0

    if "research_tier" in shadow_today.columns:
        shadow_tiers = shadow_today["research_tier"].astype(str)
        active_shadow_trades = int(shadow_tiers.eq("ACTIVE_SHADOW").sum())
        watchlist_trades = int(shadow_tiers.eq("WATCHLIST").sum())
        diagnostic_trades = int(shadow_tiers.eq("DIAGNOSTIC_ONLY").sum())
        production_reference_trades = int(shadow_tiers.eq("PRODUCTION_REFERENCE").sum())
    else:
        active_shadow_trades = 0
        watchlist_trades = 0
        diagnostic_trades = 0
        production_reference_trades = 0

    latest_audit_status, latest_audit_timestamp = get_latest_audit_status(audit)

    operating_status = "READY"
    if shadow_ready_count != len(shadow_status):
        operating_status = "CHECK_SHADOW_STATUS"
    if latest_audit_status and latest_audit_status.upper() != "PASSED":
        operating_status = "CHECK_WORKFLOW_AUDIT"

    summary_row = {
        "generated_at": generated_at,
        "review_date": review_date,
        "orb_signal_rows": int(len(signals)),
        "orb_triggered_signals": signal_counts["triggered"],
        "orb_not_triggered_signals": signal_counts["not_triggered"],
        "orb_invalid_signals": signal_counts["invalid"],
        "paper_total_trades": int(len(paper_trades)),
        "paper_open_trades": paper_open_trades,
        "paper_closed_trades": paper_closed_trades,
        "paper_opened_today": paper_opened_today,
        "paper_closed_today": paper_closed_today,
        "paper_realized_pnl_today": paper_pnl_today,
        "paper_final_account_equity": get_final_account_equity(account_curve),
        "shadow_strategy_count": int(len(shadow_status)),
        "shadow_ready_count": shadow_ready_count,
        "shadow_latest_trade_count": int(len(shadow_today)),
        "shadow_active_shadow_latest_trades": active_shadow_trades,
        "shadow_watchlist_latest_trades": watchlist_trades,
        "shadow_diagnostic_latest_trades": diagnostic_trades,
        "shadow_production_reference_latest_trades": production_reference_trades,
        "latest_audit_validation_status": latest_audit_status,
        "latest_audit_timestamp": latest_audit_timestamp,
        "operating_status": operating_status,
    }

    item_rows = []

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Production ORB",
        "Signal rows",
        "PASS" if len(signals) > 0 else "WARN",
        len(signals),
        "ORB latest signal file is populated.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Production ORB",
        "Triggered signals",
        "INFO",
        signal_counts["triggered"],
        "Triggered signals are production ORB only.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Production ORB",
        "Open paper trades",
        "INFO",
        paper_open_trades,
        "Open paper trades should be monitored separately from research shadows.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Production ORB",
        "Paper realized PnL today",
        "INFO",
        round(paper_pnl_today, 2),
        "Realized PnL from paper trades closed on the review date.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Strategy Lab Shadow",
        "Shadow definitions ready",
        "PASS" if shadow_ready_count == len(shadow_status) else "WARN",
        f"{shadow_ready_count}/{len(shadow_status)}",
        "All shadow strategy definitions should be ready before Monday operation.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Strategy Lab Shadow",
        "Latest shadow trades",
        "INFO",
        len(shadow_today),
        "Shadow trades are research-only and must not be live traded.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Audit",
        "Latest workflow audit status",
        "PASS" if latest_audit_status.upper() == "PASSED" else "WARN",
        latest_audit_status,
        "Latest workflow_run_audit validation status.",
    )

    add_item(
        item_rows,
        generated_at,
        review_date,
        "Operating Rule",
        "Production separation",
        "PASS",
        "ORB_ONLY",
        "Trade/simulate only frozen ORB production. Shadows are research-only.",
    )

    summary_df = pd.DataFrame([summary_row])
    items_df = pd.DataFrame(item_rows, columns=ITEM_COLUMNS)

    export_csv_for_power_bi(
        summary_df,
        OUTPUT_REVIEW_SUMMARY,
        columns=SUMMARY_COLUMNS,
    )

    export_csv_for_power_bi(
        items_df,
        OUTPUT_REVIEW_ITEMS,
        columns=ITEM_COLUMNS,
    )

    export_csv_for_power_bi(
        signals,
        OUTPUT_REVIEW_ORB_SIGNALS,
    )

    export_csv_for_power_bi(
        paper_today,
        OUTPUT_REVIEW_PAPER_TRADES_TODAY,
    )

    export_csv_for_power_bi(
        shadow_today,
        OUTPUT_REVIEW_SHADOW_TRADES_TODAY,
    )

    review_text = build_review_text(
        summary=summary_row,
        items=items_df,
        shadow_today=shadow_today,
        paper_today=paper_today,
    )

    OUTPUT_REVIEW_TEXT.write_text(review_text, encoding="utf-8")

    print("\n=== REVIEW SUMMARY ===")
    print(summary_df.to_string(index=False))

    print("\n=== REVIEW ITEMS ===")
    print(items_df.to_string(index=False))

    print(f"\nSaved review summary       -> {OUTPUT_REVIEW_SUMMARY}")
    print(f"Saved review items         -> {OUTPUT_REVIEW_ITEMS}")
    print(f"Saved review ORB signals   -> {OUTPUT_REVIEW_ORB_SIGNALS}")
    print(f"Saved paper trades today   -> {OUTPUT_REVIEW_PAPER_TRADES_TODAY}")
    print(f"Saved shadow trades today  -> {OUTPUT_REVIEW_SHADOW_TRADES_TODAY}")
    print(f"Saved text review          -> {OUTPUT_REVIEW_TEXT}")


if __name__ == "__main__":
    main()