from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    RESEARCH_STATUS,
    STRATEGY_ID,
)
from RegimeTrading.scripts.v1_validation_portfolio import (
    PORTFOLIO_MODEL_ID,
    load_source_trades,
    simulate_portfolio,
)


VALIDATION_SUITE_VERSION = "V1_RESEARCH_VALIDATION_SUITE_STEP2"
ANALYSIS_ID = "PROFIT_CONCENTRATION_AND_LEAVE_ONE_OUT_V1"

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
CONCENTRATION_SUMMARY_FILE = OUTPUT_DIR / "v1_validation_concentration_summary.csv"
CONCENTRATION_SCENARIOS_FILE = OUTPUT_DIR / "v1_validation_concentration_scenarios.csv"
CONTRIBUTION_DETAIL_FILE = OUTPUT_DIR / "v1_validation_contribution_detail.csv"
LEAVE_ONE_OUT_FILE = OUTPUT_DIR / "v1_validation_leave_one_out.csv"

CONTRIBUTION_LEVELS = ("TRADE", "DAY", "TICKER", "MONTH", "ISO_WEEK", "REGIME")
TOP_COUNTS = (1, 3, 5)

CONTRIBUTION_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "portfolio_model_id",
    "contribution_level",
    "rank_within_level",
    "contribution_key",
    "display_label",
    "trade_count",
    "pnl_sek",
    "positive_pnl_sek",
    "negative_pnl_sek",
    "net_pnl_share",
    "gross_profit_share",
    "cumulative_positive_profit_share",
    "is_positive_contributor",
    "source_trade_rows",
]

SCENARIO_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "portfolio_model_id",
    "scenario_order",
    "scenario_type",
    "scenario_id",
    "scenario_label",
    "requested_exclusion_count",
    "actual_exclusion_count",
    "excluded_values",
    "excluded_source_trade_rows",
    "baseline_realized_pnl_sek",
    "excluded_baseline_selected_pnl_sek",
    "direct_subtraction_pnl_sek",
    "resimulated_pnl_sek",
    "replacement_effect_sek",
    "pnl_change_vs_baseline_sek",
    "retained_pnl_ratio",
    "selected_closed_trades",
    "selected_open_trades",
    "rejected_capacity_trades",
    "win_rate",
    "profit_factor",
    "max_drawdown",
    "remains_profitable",
    "added_selected_trade_rows",
    "removed_selected_trade_rows",
]

LEAVE_ONE_OUT_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "portfolio_model_id",
    "dimension",
    "excluded_value",
    "excluded_source_trade_rows",
    "excluded_input_trade_count",
    "excluded_baseline_selected_closed_trades",
    "excluded_baseline_selected_pnl_sek",
    "baseline_realized_pnl_sek",
    "scenario_realized_pnl_sek",
    "pnl_change_vs_baseline_sek",
    "retained_pnl_ratio",
    "selected_closed_trades",
    "selected_open_trades",
    "rejected_capacity_trades",
    "win_rate",
    "profit_factor",
    "max_drawdown",
    "remains_profitable",
    "added_selected_trade_count",
    "removed_selected_trade_count",
    "added_selected_trade_rows",
    "removed_selected_trade_rows",
    "fragility_rank_within_dimension",
]

SUMMARY_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "research_status",
    "portfolio_model_id",
    "baseline_selected_closed_trades",
    "baseline_realized_pnl_sek",
    "baseline_gross_profit_sek",
    "baseline_gross_loss_sek",
    "baseline_profit_factor",
    "baseline_max_drawdown",
    "profitable_days",
    "losing_days",
    "largest_winner_sek",
    "largest_loser_sek",
    "top_1_trade_pnl_sek",
    "top_1_trade_net_pnl_share",
    "top_3_trade_pnl_sek",
    "top_3_trade_net_pnl_share",
    "top_5_trade_pnl_sek",
    "top_5_trade_net_pnl_share",
    "top_1_day_pnl_sek",
    "top_1_day_net_pnl_share",
    "top_3_day_pnl_sek",
    "top_3_day_net_pnl_share",
    "top_5_day_pnl_sek",
    "top_5_day_net_pnl_share",
    "positive_trade_concentration_hhi",
    "positive_day_concentration_hhi",
    "pnl_after_remove_top_1_trade_resim_sek",
    "pnl_after_remove_top_3_trades_resim_sek",
    "pnl_after_remove_top_5_trades_resim_sek",
    "pnl_after_remove_top_1_day_resim_sek",
    "pnl_after_remove_top_3_days_resim_sek",
    "pnl_after_remove_top_5_days_resim_sek",
    "profitable_after_remove_top_1_trade",
    "profitable_after_remove_top_3_trades",
    "profitable_after_remove_top_5_trades",
    "profitable_after_remove_top_1_day",
    "profitable_after_remove_top_3_days",
    "profitable_after_remove_top_5_days",
    "worst_leave_one_out_dimension",
    "worst_leave_one_out_value",
    "worst_leave_one_out_pnl_sek",
    "leave_one_out_scenarios",
    "leave_one_out_profitable_scenarios",
]


@dataclass
class ValidationStep2Result:
    summary: pd.DataFrame
    scenarios: pd.DataFrame
    contribution_detail: pd.DataFrame
    leave_one_out: pd.DataFrame


def _join_values(values: Iterable[object]) -> str:
    clean = [str(value) for value in values if str(value).strip()]
    return "|".join(clean)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or pd.isna(denominator):
        return np.nan
    return float(numerator) / float(denominator)


def _summary_row(result) -> pd.Series:
    if result.summary.empty:
        return pd.Series(dtype=object)
    return result.summary.iloc[0]


def _selected_closed_ids(result) -> set[int]:
    if result.ledger.empty:
        return set()
    rows = result.ledger[result.ledger["selection_status"] == "SELECTED_CLOSED"]
    return set(pd.to_numeric(rows["source_trade_row"], errors="coerce").dropna().astype(int))


def _selected_closed_ledger(result) -> pd.DataFrame:
    if result.ledger.empty:
        return result.ledger.copy()
    selected = result.ledger[result.ledger["selection_status"] == "SELECTED_CLOSED"].copy()
    selected["portfolio_pnl_sek"] = pd.to_numeric(
        selected["portfolio_pnl_sek"], errors="coerce"
    ).fillna(0.0)
    selected["source_trade_row"] = pd.to_numeric(
        selected["source_trade_row"], errors="coerce"
    ).astype("Int64")
    selected["date_dt"] = pd.to_datetime(selected["date"], errors="coerce")
    selected["month"] = selected["date_dt"].dt.strftime("%Y-%m")
    iso = selected["date_dt"].dt.isocalendar()
    selected["iso_week"] = (
        iso["year"].astype("Int64").astype(str)
        + "-W"
        + iso["week"].astype("Int64").astype(str).str.zfill(2)
    )
    return selected


def _aggregate_contributions(
    selected: pd.DataFrame,
    level: str,
    baseline_net_pnl: float,
    gross_profit: float,
) -> pd.DataFrame:
    if selected.empty:
        return pd.DataFrame(columns=CONTRIBUTION_COLUMNS)

    if level == "TRADE":
        aggregated = selected.copy()
        aggregated["contribution_key"] = aggregated["source_trade_row"].astype(str)
        aggregated["display_label"] = (
            aggregated["date"].astype(str)
            + " | "
            + aggregated["ticker"].astype(str)
            + " | row "
            + aggregated["source_trade_row"].astype(str)
        )
        aggregated["trade_count"] = 1
        aggregated["pnl_sek"] = aggregated["portfolio_pnl_sek"]
        aggregated["source_trade_rows"] = aggregated["source_trade_row"].astype(str)
        aggregated = aggregated[
            [
                "contribution_key",
                "display_label",
                "trade_count",
                "pnl_sek",
                "source_trade_rows",
            ]
        ]
    else:
        column_map = {
            "DAY": "date",
            "TICKER": "ticker",
            "MONTH": "month",
            "ISO_WEEK": "iso_week",
            "REGIME": "early_market_regime",
        }
        group_column = column_map[level]
        work = selected.copy()
        work[group_column] = work[group_column].fillna("UNKNOWN").astype(str)
        aggregated = (
            work.groupby(group_column, dropna=False)
            .agg(
                trade_count=("source_trade_row", "size"),
                pnl_sek=("portfolio_pnl_sek", "sum"),
                source_trade_rows=(
                    "source_trade_row",
                    lambda series: _join_values(sorted(int(v) for v in series.dropna())),
                ),
            )
            .reset_index()
            .rename(columns={group_column: "contribution_key"})
        )
        aggregated["display_label"] = aggregated["contribution_key"]

    aggregated["positive_pnl_sek"] = aggregated["pnl_sek"].clip(lower=0.0)
    aggregated["negative_pnl_sek"] = aggregated["pnl_sek"].clip(upper=0.0)
    aggregated = aggregated.sort_values(
        ["pnl_sek", "contribution_key"], ascending=[False, True]
    ).reset_index(drop=True)
    aggregated["rank_within_level"] = np.arange(1, len(aggregated) + 1)
    aggregated["net_pnl_share"] = aggregated["pnl_sek"].apply(
        lambda value: _safe_ratio(float(value), baseline_net_pnl)
    )
    aggregated["gross_profit_share"] = aggregated["positive_pnl_sek"].apply(
        lambda value: _safe_ratio(float(value), gross_profit)
    )
    aggregated["cumulative_positive_profit_share"] = (
        aggregated["positive_pnl_sek"].cumsum() / gross_profit
        if gross_profit > 0
        else np.nan
    )
    aggregated["is_positive_contributor"] = aggregated["pnl_sek"] > 0
    aggregated["validation_suite_version"] = VALIDATION_SUITE_VERSION
    aggregated["analysis_id"] = ANALYSIS_ID
    aggregated["strategy_id"] = STRATEGY_ID
    aggregated["portfolio_model_id"] = PORTFOLIO_MODEL_ID
    aggregated["contribution_level"] = level

    return aggregated[CONTRIBUTION_COLUMNS]


def build_contribution_detail(baseline_result) -> pd.DataFrame:
    selected = _selected_closed_ledger(baseline_result)
    summary = _summary_row(baseline_result)
    baseline_net = float(summary.get("total_realized_pnl_sek", 0.0))
    gross_profit = float(summary.get("gross_profit_sek", 0.0))
    frames = [
        _aggregate_contributions(selected, level, baseline_net, gross_profit)
        for level in CONTRIBUTION_LEVELS
    ]
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        return pd.DataFrame(columns=CONTRIBUTION_COLUMNS)
    return pd.concat(nonempty, ignore_index=True)[CONTRIBUTION_COLUMNS]


def _simulate_after_exclusion(
    trades: pd.DataFrame,
    excluded_source_rows: set[int],
):
    if not excluded_source_rows:
        return simulate_portfolio(trades.copy())
    source_rows = pd.to_numeric(trades["source_trade_row"], errors="coerce").astype("Int64")
    filtered = trades[~source_rows.isin(excluded_source_rows)].copy()
    return simulate_portfolio(filtered)


def _scenario_record(
    *,
    order: int,
    scenario_type: str,
    scenario_id: str,
    scenario_label: str,
    requested_count: int,
    excluded_values: list[str],
    excluded_rows: set[int],
    excluded_baseline_selected_pnl: float,
    baseline_result,
    scenario_result,
) -> dict:
    baseline_summary = _summary_row(baseline_result)
    scenario_summary = _summary_row(scenario_result)
    baseline_pnl = float(baseline_summary.get("total_realized_pnl_sek", 0.0))
    scenario_pnl = float(scenario_summary.get("total_realized_pnl_sek", 0.0))
    direct_pnl = baseline_pnl - float(excluded_baseline_selected_pnl)
    baseline_ids = _selected_closed_ids(baseline_result)
    scenario_ids = _selected_closed_ids(scenario_result)
    added = sorted(scenario_ids - baseline_ids)
    removed = sorted(baseline_ids - scenario_ids)

    return {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "analysis_id": ANALYSIS_ID,
        "strategy_id": STRATEGY_ID,
        "portfolio_model_id": PORTFOLIO_MODEL_ID,
        "scenario_order": int(order),
        "scenario_type": scenario_type,
        "scenario_id": scenario_id,
        "scenario_label": scenario_label,
        "requested_exclusion_count": int(requested_count),
        "actual_exclusion_count": int(len(excluded_values)),
        "excluded_values": _join_values(excluded_values),
        "excluded_source_trade_rows": _join_values(sorted(excluded_rows)),
        "baseline_realized_pnl_sek": baseline_pnl,
        "excluded_baseline_selected_pnl_sek": float(excluded_baseline_selected_pnl),
        "direct_subtraction_pnl_sek": direct_pnl,
        "resimulated_pnl_sek": scenario_pnl,
        "replacement_effect_sek": scenario_pnl - direct_pnl,
        "pnl_change_vs_baseline_sek": scenario_pnl - baseline_pnl,
        "retained_pnl_ratio": _safe_ratio(scenario_pnl, baseline_pnl),
        "selected_closed_trades": int(scenario_summary.get("selected_closed_trades", 0)),
        "selected_open_trades": int(scenario_summary.get("selected_open_trades", 0)),
        "rejected_capacity_trades": int(scenario_summary.get("rejected_capacity_trades", 0)),
        "win_rate": scenario_summary.get("win_rate", np.nan),
        "profit_factor": scenario_summary.get("profit_factor", np.nan),
        "max_drawdown": scenario_summary.get("max_drawdown", np.nan),
        "remains_profitable": bool(scenario_pnl > 0),
        "added_selected_trade_rows": _join_values(added),
        "removed_selected_trade_rows": _join_values(removed),
    }


def build_concentration_scenarios(trades: pd.DataFrame, baseline_result) -> pd.DataFrame:
    selected = _selected_closed_ledger(baseline_result)
    rows: list[dict] = []
    rows.append(
        _scenario_record(
            order=0,
            scenario_type="BASELINE",
            scenario_id="BASELINE",
            scenario_label="Baseline max-two-position portfolio",
            requested_count=0,
            excluded_values=[],
            excluded_rows=set(),
            excluded_baseline_selected_pnl=0.0,
            baseline_result=baseline_result,
            scenario_result=baseline_result,
        )
    )

    positive_trades = selected[selected["portfolio_pnl_sek"] > 0].sort_values(
        ["portfolio_pnl_sek", "source_trade_row"], ascending=[False, True]
    )
    day_pnl = (
        selected.groupby("date", dropna=False)["portfolio_pnl_sek"]
        .sum()
        .sort_values(ascending=False)
    )
    positive_days = day_pnl[day_pnl > 0]

    order = 1
    for requested_count in TOP_COUNTS:
        chosen = positive_trades.head(requested_count)
        chosen_rows = set(chosen["source_trade_row"].dropna().astype(int))
        values = [
            f"{row.date}:{row.ticker}:row{int(row.source_trade_row)}"
            for row in chosen.itertuples()
        ]
        scenario = _simulate_after_exclusion(trades, chosen_rows)
        rows.append(
            _scenario_record(
                order=order,
                scenario_type="EXCLUDE_TOP_TRADES",
                scenario_id=f"EXCLUDE_TOP_{requested_count}_TRADES",
                scenario_label=f"Exclude baseline top {requested_count} profitable trade(s)",
                requested_count=requested_count,
                excluded_values=values,
                excluded_rows=chosen_rows,
                excluded_baseline_selected_pnl=float(chosen["portfolio_pnl_sek"].sum()),
                baseline_result=baseline_result,
                scenario_result=scenario,
            )
        )
        order += 1

    for requested_count in TOP_COUNTS:
        chosen_days = [str(value) for value in positive_days.head(requested_count).index]
        trade_dates = trades["date"].fillna("").astype(str)
        excluded_rows = set(
            pd.to_numeric(
                trades.loc[trade_dates.isin(chosen_days), "source_trade_row"],
                errors="coerce",
            )
            .dropna()
            .astype(int)
        )
        scenario = _simulate_after_exclusion(trades, excluded_rows)
        rows.append(
            _scenario_record(
                order=order,
                scenario_type="EXCLUDE_TOP_DAYS",
                scenario_id=f"EXCLUDE_TOP_{requested_count}_DAYS",
                scenario_label=f"Exclude baseline top {requested_count} profitable day(s)",
                requested_count=requested_count,
                excluded_values=chosen_days,
                excluded_rows=excluded_rows,
                excluded_baseline_selected_pnl=float(positive_days.head(requested_count).sum()),
                baseline_result=baseline_result,
                scenario_result=scenario,
            )
        )
        order += 1

    return pd.DataFrame(rows, columns=SCENARIO_COLUMNS)


def _dimension_series(trades: pd.DataFrame, dimension: str) -> pd.Series:
    if dimension == "TICKER":
        return trades["ticker"].fillna("UNKNOWN").astype(str)
    if dimension == "REGIME":
        return trades["early_market_regime"].fillna("UNKNOWN").astype(str)

    date_values = pd.to_datetime(trades["date"], errors="coerce")
    if dimension == "MONTH":
        return date_values.dt.strftime("%Y-%m").fillna("UNKNOWN")
    if dimension == "ISO_WEEK":
        iso = date_values.dt.isocalendar()
        result = (
            iso["year"].astype("Int64").astype(str)
            + "-W"
            + iso["week"].astype("Int64").astype(str).str.zfill(2)
        )
        return result.fillna("UNKNOWN")
    raise ValueError(f"Unsupported leave-one-out dimension: {dimension}")


def build_leave_one_out(trades: pd.DataFrame, baseline_result) -> pd.DataFrame:
    baseline_summary = _summary_row(baseline_result)
    baseline_pnl = float(baseline_summary.get("total_realized_pnl_sek", 0.0))
    baseline_ledger = _selected_closed_ledger(baseline_result)
    baseline_ids = _selected_closed_ids(baseline_result)
    records: list[dict] = []

    for dimension in ("TICKER", "MONTH", "ISO_WEEK", "REGIME"):
        values = _dimension_series(trades, dimension)
        for excluded_value in sorted(values.dropna().astype(str).unique()):
            mask = values.astype(str) == str(excluded_value)
            excluded_rows = set(
                pd.to_numeric(trades.loc[mask, "source_trade_row"], errors="coerce")
                .dropna()
                .astype(int)
            )
            scenario_result = _simulate_after_exclusion(trades, excluded_rows)
            scenario_summary = _summary_row(scenario_result)
            scenario_pnl = float(scenario_summary.get("total_realized_pnl_sek", 0.0))
            scenario_ids = _selected_closed_ids(scenario_result)
            added = sorted(scenario_ids - baseline_ids)
            removed = sorted(baseline_ids - scenario_ids)
            baseline_removed = baseline_ledger[
                baseline_ledger["source_trade_row"].isin(excluded_rows)
            ]

            records.append(
                {
                    "validation_suite_version": VALIDATION_SUITE_VERSION,
                    "analysis_id": ANALYSIS_ID,
                    "strategy_id": STRATEGY_ID,
                    "portfolio_model_id": PORTFOLIO_MODEL_ID,
                    "dimension": dimension,
                    "excluded_value": str(excluded_value),
                    "excluded_source_trade_rows": _join_values(sorted(excluded_rows)),
                    "excluded_input_trade_count": int(mask.sum()),
                    "excluded_baseline_selected_closed_trades": int(len(baseline_removed)),
                    "excluded_baseline_selected_pnl_sek": float(
                        baseline_removed["portfolio_pnl_sek"].sum()
                    ),
                    "baseline_realized_pnl_sek": baseline_pnl,
                    "scenario_realized_pnl_sek": scenario_pnl,
                    "pnl_change_vs_baseline_sek": scenario_pnl - baseline_pnl,
                    "retained_pnl_ratio": _safe_ratio(scenario_pnl, baseline_pnl),
                    "selected_closed_trades": int(
                        scenario_summary.get("selected_closed_trades", 0)
                    ),
                    "selected_open_trades": int(
                        scenario_summary.get("selected_open_trades", 0)
                    ),
                    "rejected_capacity_trades": int(
                        scenario_summary.get("rejected_capacity_trades", 0)
                    ),
                    "win_rate": scenario_summary.get("win_rate", np.nan),
                    "profit_factor": scenario_summary.get("profit_factor", np.nan),
                    "max_drawdown": scenario_summary.get("max_drawdown", np.nan),
                    "remains_profitable": bool(scenario_pnl > 0),
                    "added_selected_trade_count": int(len(added)),
                    "removed_selected_trade_count": int(len(removed)),
                    "added_selected_trade_rows": _join_values(added),
                    "removed_selected_trade_rows": _join_values(removed),
                    "fragility_rank_within_dimension": 0,
                }
            )

    result = pd.DataFrame(records, columns=LEAVE_ONE_OUT_COLUMNS)
    if result.empty:
        return result
    result["fragility_rank_within_dimension"] = (
        result.groupby("dimension")["scenario_realized_pnl_sek"]
        .rank(method="first", ascending=True)
        .astype(int)
    )
    return result.sort_values(
        ["dimension", "fragility_rank_within_dimension", "excluded_value"]
    ).reset_index(drop=True)[LEAVE_ONE_OUT_COLUMNS]


def _top_positive_sum(detail: pd.DataFrame, level: str, count: int) -> float:
    subset = detail[
        (detail["contribution_level"] == level)
        & (detail["pnl_sek"] > 0)
    ].sort_values("rank_within_level")
    return float(pd.to_numeric(subset.head(count)["pnl_sek"], errors="coerce").sum())


def _positive_hhi(detail: pd.DataFrame, level: str) -> float:
    subset = detail[
        (detail["contribution_level"] == level)
        & (detail["positive_pnl_sek"] > 0)
    ]
    shares = pd.to_numeric(subset["gross_profit_share"], errors="coerce").dropna()
    return float((shares**2).sum()) if not shares.empty else np.nan


def build_summary(
    baseline_result,
    contribution_detail: pd.DataFrame,
    scenarios: pd.DataFrame,
    leave_one_out: pd.DataFrame,
) -> pd.DataFrame:
    baseline = _summary_row(baseline_result)
    selected = _selected_closed_ledger(baseline_result)
    baseline_pnl = float(baseline.get("total_realized_pnl_sek", 0.0))
    day_pnl = selected.groupby("date")["portfolio_pnl_sek"].sum() if not selected.empty else pd.Series(dtype=float)

    scenario_lookup = scenarios.set_index("scenario_id") if not scenarios.empty else pd.DataFrame()

    def scenario_pnl(scenario_id: str) -> float:
        if scenario_lookup.empty or scenario_id not in scenario_lookup.index:
            return np.nan
        return float(scenario_lookup.loc[scenario_id, "resimulated_pnl_sek"])

    def scenario_positive(scenario_id: str) -> bool:
        value = scenario_pnl(scenario_id)
        return bool(value > 0) if pd.notna(value) else False

    worst_dimension = ""
    worst_value = ""
    worst_pnl = np.nan
    if not leave_one_out.empty:
        worst = leave_one_out.sort_values("scenario_realized_pnl_sek").iloc[0]
        worst_dimension = str(worst["dimension"])
        worst_value = str(worst["excluded_value"])
        worst_pnl = float(worst["scenario_realized_pnl_sek"])

    row = {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "analysis_id": ANALYSIS_ID,
        "strategy_id": STRATEGY_ID,
        "research_status": RESEARCH_STATUS,
        "portfolio_model_id": PORTFOLIO_MODEL_ID,
        "baseline_selected_closed_trades": int(baseline.get("selected_closed_trades", 0)),
        "baseline_realized_pnl_sek": baseline_pnl,
        "baseline_gross_profit_sek": float(baseline.get("gross_profit_sek", 0.0)),
        "baseline_gross_loss_sek": float(baseline.get("gross_loss_sek", 0.0)),
        "baseline_profit_factor": baseline.get("profit_factor", np.nan),
        "baseline_max_drawdown": baseline.get("max_drawdown", np.nan),
        "profitable_days": int((day_pnl > 0).sum()),
        "losing_days": int((day_pnl < 0).sum()),
        "largest_winner_sek": float(selected["portfolio_pnl_sek"].max()) if not selected.empty else np.nan,
        "largest_loser_sek": float(selected["portfolio_pnl_sek"].min()) if not selected.empty else np.nan,
        "positive_trade_concentration_hhi": _positive_hhi(contribution_detail, "TRADE"),
        "positive_day_concentration_hhi": _positive_hhi(contribution_detail, "DAY"),
        "pnl_after_remove_top_1_trade_resim_sek": scenario_pnl("EXCLUDE_TOP_1_TRADES"),
        "pnl_after_remove_top_3_trades_resim_sek": scenario_pnl("EXCLUDE_TOP_3_TRADES"),
        "pnl_after_remove_top_5_trades_resim_sek": scenario_pnl("EXCLUDE_TOP_5_TRADES"),
        "pnl_after_remove_top_1_day_resim_sek": scenario_pnl("EXCLUDE_TOP_1_DAYS"),
        "pnl_after_remove_top_3_days_resim_sek": scenario_pnl("EXCLUDE_TOP_3_DAYS"),
        "pnl_after_remove_top_5_days_resim_sek": scenario_pnl("EXCLUDE_TOP_5_DAYS"),
        "profitable_after_remove_top_1_trade": scenario_positive("EXCLUDE_TOP_1_TRADES"),
        "profitable_after_remove_top_3_trades": scenario_positive("EXCLUDE_TOP_3_TRADES"),
        "profitable_after_remove_top_5_trades": scenario_positive("EXCLUDE_TOP_5_TRADES"),
        "profitable_after_remove_top_1_day": scenario_positive("EXCLUDE_TOP_1_DAYS"),
        "profitable_after_remove_top_3_days": scenario_positive("EXCLUDE_TOP_3_DAYS"),
        "profitable_after_remove_top_5_days": scenario_positive("EXCLUDE_TOP_5_DAYS"),
        "worst_leave_one_out_dimension": worst_dimension,
        "worst_leave_one_out_value": worst_value,
        "worst_leave_one_out_pnl_sek": worst_pnl,
        "leave_one_out_scenarios": int(len(leave_one_out)),
        "leave_one_out_profitable_scenarios": int(
            leave_one_out["remains_profitable"].fillna(False).astype(bool).sum()
        ) if not leave_one_out.empty else 0,
    }

    for level_key, label in (("TRADE", "trade"), ("DAY", "day")):
        for count in TOP_COUNTS:
            pnl_value = _top_positive_sum(contribution_detail, level_key, count)
            row[f"top_{count}_{label}_pnl_sek"] = pnl_value
            row[f"top_{count}_{label}_net_pnl_share"] = _safe_ratio(pnl_value, baseline_pnl)

    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_step2(trades: pd.DataFrame | None = None) -> ValidationStep2Result:
    source = load_source_trades() if trades is None else trades.copy()
    baseline_result = simulate_portfolio(source)
    contribution = build_contribution_detail(baseline_result)
    scenarios = build_concentration_scenarios(source, baseline_result)
    leave_one_out = build_leave_one_out(source, baseline_result)
    summary = build_summary(baseline_result, contribution, scenarios, leave_one_out)
    return ValidationStep2Result(
        summary=summary,
        scenarios=scenarios,
        contribution_detail=contribution,
        leave_one_out=leave_one_out,
    )


def export_result(result: ValidationStep2Result) -> None:
    outputs = {
        CONCENTRATION_SUMMARY_FILE: result.summary,
        CONCENTRATION_SCENARIOS_FILE: result.scenarios,
        CONTRIBUTION_DETAIL_FILE: result.contribution_detail,
        LEAVE_ONE_OUT_FILE: result.leave_one_out,
    }
    for path, frame in outputs.items():
        export_csv_for_power_bi(frame, path)
        print(f"Saved {path.name}: {len(frame)} rows")


def main() -> None:
    print("\n=== V1 RESEARCH VALIDATION SUITE - STEP 2 ===")
    print("Module          : Profit concentration and leave-one-out analysis")
    print(f"Strategy        : {STRATEGY_ID}")
    print(f"Portfolio model : {PORTFOLIO_MODEL_ID}")
    print("Method          : Re-simulate max-two-position portfolio after every exclusion")
    print("V1 rules and Step 1 portfolio assumptions are not changed.")

    result = run_step2()
    export_result(result)
    row = result.summary.iloc[0]

    print("\n=== CONCENTRATION RESULT ===")
    print(f"Baseline realized PnL           : {float(row['baseline_realized_pnl_sek']):.2f} SEK")
    print(f"Top 1 trade share of net PnL    : {float(row['top_1_trade_net_pnl_share']):.2%}")
    print(f"Top 3 trades share of net PnL   : {float(row['top_3_trade_net_pnl_share']):.2%}")
    print(f"Top 1 day share of net PnL      : {float(row['top_1_day_net_pnl_share']):.2%}")
    print(f"Top 3 days share of net PnL     : {float(row['top_3_day_net_pnl_share']):.2%}")
    print(
        "PnL without top 3 trades      : "
        f"{float(row['pnl_after_remove_top_3_trades_resim_sek']):.2f} SEK"
    )
    print(
        "PnL without top 3 days        : "
        f"{float(row['pnl_after_remove_top_3_days_resim_sek']):.2f} SEK"
    )
    print(
        "Profitable leave-one-out cases: "
        f"{int(row['leave_one_out_profitable_scenarios'])}/"
        f"{int(row['leave_one_out_scenarios'])}"
    )
    print(
        "Worst leave-one-out case      : "
        f"{row['worst_leave_one_out_dimension']}={row['worst_leave_one_out_value']} "
        f"-> {float(row['worst_leave_one_out_pnl_sek']):.2f} SEK"
    )
    print("Step 2 validation export complete.")


if __name__ == "__main__":
    main()
