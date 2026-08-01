from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.execution import execute_long_orb_trade
from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.core.research_config import (
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_POSITION_SIZE,
)
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    EOD_EXIT_TIME,
    ENTRY_WINDOW_START,
    FAVORABLE_REGIMES,
    GAP_RECOVERY_TICKERS,
    OPENING_RANGE_START,
    RESEARCH_STATUS,
    SAME_BAR_PRIORITY,
    STRATEGY_ID,
    build_daily_reference,
    calculate_early_market_regime,
    load_intraday_prices,
)
from RegimeTrading.scripts.v1_validation_portfolio import simulate_portfolio


VALIDATION_SUITE_VERSION = "V1_RESEARCH_VALIDATION_SUITE_STEP4"
MODULE_ID = "PARAMETER_ROBUSTNESS_V1"
ANALYSIS_MODE = "COMPLETED_SESSIONS_ONLY"
REGIME_POLICY = "V1_EARLY_REGIME_FIXED"
EXECUTION_POLICY = "V1_SHARED_EXECUTION_STOP_PRIORITY"
POSITION_SIZE_SEK = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
SUMMARY_FILE = OUTPUT_DIR / "v1_validation_parameter_robustness_summary.csv"
SCENARIOS_FILE = OUTPUT_DIR / "v1_validation_parameter_robustness_scenarios.csv"
SENSITIVITY_FILE = OUTPUT_DIR / "v1_validation_parameter_sensitivity.csv"
RECONCILIATION_FILE = OUTPUT_DIR / "v1_validation_parameter_baseline_reconciliation.csv"


@dataclass(frozen=True)
class ParameterScenario:
    scenario_id: str
    scenario_family: str
    changed_dimension: str
    min_gap: float = -0.0200
    max_gap: float = -0.0010
    opening_range_minutes: int = 5
    entry_window_end: str = "13:00"
    target_recovery_fraction: float = 1.00
    max_risk_pct: float | None = None

    @property
    def distance_from_v1(self) -> int:
        baseline = baseline_scenario()
        values = [
            self.min_gap != baseline.min_gap,
            self.max_gap != baseline.max_gap,
            self.opening_range_minutes != baseline.opening_range_minutes,
            self.entry_window_end != baseline.entry_window_end,
            self.target_recovery_fraction != baseline.target_recovery_fraction,
            self.max_risk_pct != baseline.max_risk_pct,
        ]
        return int(sum(values))


def baseline_scenario() -> ParameterScenario:
    return ParameterScenario(
        scenario_id="V1_BASELINE",
        scenario_family="BASELINE",
        changed_dimension="NONE",
    )


SUMMARY_COLUMNS = [
    "validation_suite_version",
    "module_id",
    "strategy_id",
    "research_status",
    "analysis_mode",
    "regime_policy",
    "execution_policy",
    "analysis_start_date",
    "analysis_end_date",
    "complete_session_dates",
    "excluded_incomplete_dates",
    "baseline_scenario_id",
    "baseline_candidate_count",
    "baseline_triggered_trades",
    "baseline_selected_closed_trades",
    "baseline_rejected_capacity_trades",
    "baseline_realized_pnl_sek",
    "baseline_profit_factor",
    "baseline_max_drawdown",
    "scenario_count",
    "profitable_scenario_count",
    "profitable_scenario_share",
    "one_at_a_time_scenario_count",
    "one_at_a_time_profitable_count",
    "one_at_a_time_profitable_share",
    "core_neighborhood_scenario_count",
    "core_neighborhood_profitable_count",
    "core_neighborhood_profitable_share",
    "core_neighborhood_median_pnl_sek",
    "core_neighborhood_p25_pnl_sek",
    "core_neighborhood_min_pnl_sek",
    "core_neighborhood_max_pnl_sek",
    "core_neighborhood_median_retained_pnl_ratio",
    "best_scenario_id",
    "best_scenario_pnl_sek",
    "worst_scenario_id",
    "worst_scenario_pnl_sek",
    "baseline_rank_by_pnl",
    "baseline_percentile_by_pnl",
    "robustness_classification",
]

SCENARIO_COLUMNS = [
    "validation_suite_version",
    "module_id",
    "scenario_id",
    "scenario_family",
    "changed_dimension",
    "distance_from_v1",
    "min_gap",
    "max_gap",
    "opening_range_minutes",
    "entry_window_end",
    "target_recovery_fraction",
    "max_risk_pct",
    "candidate_count",
    "valid_setup_count",
    "triggered_trade_count",
    "selected_trade_count",
    "selected_closed_trades",
    "rejected_capacity_trades",
    "win_rate",
    "profit_factor",
    "realized_pnl_sek",
    "total_return",
    "max_drawdown",
    "avg_r_multiple",
    "pnl_change_vs_baseline_sek",
    "retained_pnl_ratio_vs_baseline",
    "profitable",
    "rank_by_pnl",
    "analysis_start_date",
    "analysis_end_date",
]

SENSITIVITY_COLUMNS = [
    "validation_suite_version",
    "module_id",
    "dimension",
    "parameter_value",
    "scenario_count",
    "profitable_scenario_count",
    "profitable_scenario_share",
    "median_realized_pnl_sek",
    "mean_realized_pnl_sek",
    "min_realized_pnl_sek",
    "max_realized_pnl_sek",
    "median_retained_pnl_ratio",
    "median_selected_closed_trades",
    "median_profit_factor",
    "median_max_drawdown",
]

RECONCILIATION_COLUMNS = [
    "validation_suite_version",
    "module_id",
    "date",
    "session_status",
    "research_ticker_count",
    "complete_ticker_count",
    "minimum_last_bar_time",
    "maximum_last_bar_time",
    "included_in_parameter_analysis",
]


def _clock_string(value: pd.Timestamp) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%H:%M")


def build_session_reconciliation(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=RECONCILIATION_COLUMNS)

    universe = prices[prices["ticker"].isin(GAP_RECOVERY_TICKERS)].copy()
    if universe.empty:
        return pd.DataFrame(columns=RECONCILIATION_COLUMNS)

    per_ticker = (
        universe.groupby(["date", "ticker"], as_index=False)
        .agg(last_bar=("datetime", "max"))
    )
    per_ticker["is_complete"] = per_ticker["last_bar"].dt.strftime("%H:%M").ge(EOD_EXIT_TIME)

    rows: list[dict] = []
    expected = len(GAP_RECOVERY_TICKERS)
    for date_value, day in per_ticker.groupby("date", sort=True):
        ticker_count = int(day["ticker"].nunique())
        complete_count = int(day["is_complete"].sum())
        included = ticker_count == expected and complete_count == expected
        rows.append(
            {
                "validation_suite_version": VALIDATION_SUITE_VERSION,
                "module_id": MODULE_ID,
                "date": date_value.isoformat(),
                "session_status": "COMPLETE" if included else "INCOMPLETE",
                "research_ticker_count": ticker_count,
                "complete_ticker_count": complete_count,
                "minimum_last_bar_time": _clock_string(day["last_bar"].min()),
                "maximum_last_bar_time": _clock_string(day["last_bar"].max()),
                "included_in_parameter_analysis": included,
            }
        )

    return pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS)


def completed_dates_from_reconciliation(reconciliation: pd.DataFrame) -> set:
    if reconciliation.empty:
        return set()
    included = reconciliation[reconciliation["included_in_parameter_analysis"].fillna(False)]
    return set(pd.to_datetime(included["date"], errors="coerce").dt.date.dropna())


def _opening_range_end(minutes: int) -> str:
    base = datetime.strptime(OPENING_RANGE_START, "%H:%M")
    return (base + timedelta(minutes=int(minutes))).strftime("%H:%M")


def _first_crossing_bar(bars: pd.DataFrame, trigger: float) -> pd.Series | None:
    crossed = bars[bars["high"] >= trigger]
    if crossed.empty:
        return None
    return crossed.iloc[0]


def _prepare_sessions(prices: pd.DataFrame, complete_dates: set) -> dict[tuple[str, object], pd.DataFrame]:
    filtered = prices[
        prices["ticker"].isin(GAP_RECOVERY_TICKERS)
        & prices["date"].isin(complete_dates)
    ].copy()
    return {
        (ticker, date_value): group.sort_values("datetime").reset_index(drop=True)
        for (ticker, date_value), group in filtered.groupby(["ticker", "date"], sort=True)
    }


def _build_parameter_trades(
    scenario: ParameterScenario,
    sessions: dict[tuple[str, object], pd.DataFrame],
    daily_reference: pd.DataFrame,
    early_regime: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    reference_lookup = daily_reference.set_index(["ticker", "date"]).to_dict("index")
    regime_lookup = early_regime.set_index("date").to_dict("index") if not early_regime.empty else {}
    opening_end = _opening_range_end(scenario.opening_range_minutes)

    trade_rows: list[dict] = []
    candidate_count = 0
    valid_setup_count = 0

    for (ticker, session_date), bars in sessions.items():
        candidate_count += 1
        reference = reference_lookup.get((ticker, session_date), {})
        open_price = pd.to_numeric(reference.get("open_price"), errors="coerce")
        previous_close = pd.to_numeric(reference.get("previous_close"), errors="coerce")
        if pd.isna(open_price) or pd.isna(previous_close) or open_price <= 0 or previous_close <= 0:
            continue

        gap = float(open_price / previous_close - 1.0)
        if gap >= 0 or gap < scenario.min_gap or gap > scenario.max_gap:
            continue

        regime = regime_lookup.get(session_date, {})
        if str(regime.get("early_market_regime", "INSUFFICIENT_DATA")) not in FAVORABLE_REGIMES:
            continue

        clocks = bars["datetime"].dt.strftime("%H:%M")
        opening = bars[clocks.ge(OPENING_RANGE_START) & clocks.lt(opening_end)].copy()
        if opening.empty:
            continue

        entry_price = float(opening["high"].max())
        stop_price = float(opening["low"].min())
        if not np.isfinite(entry_price) or not np.isfinite(stop_price) or stop_price >= entry_price:
            continue

        risk_pct = (entry_price - stop_price) / entry_price
        if scenario.max_risk_pct is not None and risk_pct > scenario.max_risk_pct:
            continue

        target_price = entry_price + scenario.target_recovery_fraction * (float(previous_close) - entry_price)
        if target_price <= entry_price:
            continue

        valid_setup_count += 1
        entry_window = bars[
            clocks.ge(ENTRY_WINDOW_START) & clocks.le(scenario.entry_window_end)
        ].copy()
        entry_bar = _first_crossing_bar(entry_window, entry_price)
        if entry_bar is None:
            continue

        reported_entry_time = pd.Timestamp(entry_bar["datetime"])
        helper_entry_time = reported_entry_time - pd.Timedelta(microseconds=1)
        result = execute_long_orb_trade(
            entry_time=helper_entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            bars=bars,
            timestamp_col="datetime",
            close_if_no_hit=True,
            same_bar_priority=SAME_BAR_PRIORITY,
            eod_exit_time=EOD_EXIT_TIME,
        )
        if result.status != "CLOSED":
            continue

        net_pnl_pct = float(result.pnl_pct) - float(ORB_COST_PER_TRADE)
        reward_risk = (target_price - entry_price) / (entry_price - stop_price)
        trade_rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "research_status": RESEARCH_STATUS,
                "date": session_date.isoformat(),
                "ticker": ticker,
                "entry_time": reported_entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "exit_time": result.exit_time,
                "exit_price": result.exit_price,
                "exit_reason": result.exit_reason,
                "pnl_pct": net_pnl_pct,
                "position_size_sek": POSITION_SIZE_SEK,
                "r_multiple_achieved": result.r_multiple_achieved,
                "gap": gap,
                "gap_pct": gap * 100.0,
                "opening_range_pct": (entry_price - stop_price) / float(open_price),
                "risk_pct": risk_pct,
                "reward_risk": reward_risk,
                "early_market_regime": str(regime.get("early_market_regime", "")),
                "research_universe": "PARAMETER_ROBUSTNESS",
            }
        )

    return pd.DataFrame(trade_rows), candidate_count, valid_setup_count


def generate_scenarios() -> list[ParameterScenario]:
    baseline = baseline_scenario()
    scenarios: list[ParameterScenario] = [baseline]

    oat_values = {
        "MIN_GAP": [(-0.0150, "-1.50%"), (-0.0250, "-2.50%"), (-0.0300, "-3.00%")],
        "MAX_GAP": [(-0.0005, "-0.05%"), (-0.0020, "-0.20%"), (-0.0030, "-0.30%")],
        "OPENING_RANGE_MINUTES": [(10, "10"), (15, "15")],
        "ENTRY_WINDOW_END": [("11:00", "11:00"), ("12:00", "12:00"), ("14:00", "14:00")],
        "TARGET_RECOVERY_FRACTION": [(0.75, "0.75"), (1.25, "1.25")],
        "MAX_RISK_PCT": [(0.0100, "1.00%"), (0.0150, "1.50%"), (0.0200, "2.00%"), (0.0250, "2.50%")],
    }

    for dimension, values in oat_values.items():
        for value, label in values:
            kwargs = {
                "scenario_id": f"OAT_{dimension}_{label}",
                "scenario_family": "ONE_AT_A_TIME",
                "changed_dimension": dimension,
            }
            if dimension == "MIN_GAP":
                kwargs["min_gap"] = value
            elif dimension == "MAX_GAP":
                kwargs["max_gap"] = value
            elif dimension == "OPENING_RANGE_MINUTES":
                kwargs["opening_range_minutes"] = value
            elif dimension == "ENTRY_WINDOW_END":
                kwargs["entry_window_end"] = value
            elif dimension == "TARGET_RECOVERY_FRACTION":
                kwargs["target_recovery_fraction"] = value
            elif dimension == "MAX_RISK_PCT":
                kwargs["max_risk_pct"] = value
            scenarios.append(replace(baseline, **kwargs))

    grid_values = product(
        [-0.0150, -0.0200, -0.0250],
        [-0.0005, -0.0010, -0.0020],
        [5, 10],
        ["12:00", "13:00", "14:00"],
        [0.75, 1.00],
        [None, 0.0200],
    )
    for index, (min_gap, max_gap, or_minutes, cutoff, target_fraction, max_risk) in enumerate(grid_values, start=1):
        scenarios.append(
            ParameterScenario(
                scenario_id=f"CORE_GRID_{index:03d}",
                scenario_family="CORE_NEIGHBORHOOD",
                changed_dimension="MULTI_PARAMETER",
                min_gap=min_gap,
                max_gap=max_gap,
                opening_range_minutes=or_minutes,
                entry_window_end=cutoff,
                target_recovery_fraction=target_fraction,
                max_risk_pct=max_risk,
            )
        )

    return scenarios


def _scenario_row(
    scenario: ParameterScenario,
    trades: pd.DataFrame,
    candidate_count: int,
    valid_setup_count: int,
    analysis_start_date: str,
    analysis_end_date: str,
) -> dict:
    simulation = simulate_portfolio(trades)
    summary = simulation.summary.iloc[0]
    return {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "module_id": MODULE_ID,
        "scenario_id": scenario.scenario_id,
        "scenario_family": scenario.scenario_family,
        "changed_dimension": scenario.changed_dimension,
        "distance_from_v1": scenario.distance_from_v1,
        "min_gap": scenario.min_gap,
        "max_gap": scenario.max_gap,
        "opening_range_minutes": scenario.opening_range_minutes,
        "entry_window_end": scenario.entry_window_end,
        "target_recovery_fraction": scenario.target_recovery_fraction,
        "max_risk_pct": scenario.max_risk_pct,
        "candidate_count": candidate_count,
        "valid_setup_count": valid_setup_count,
        "triggered_trade_count": int(len(trades)),
        "selected_trade_count": int(summary["selected_trade_rows"]),
        "selected_closed_trades": int(summary["selected_closed_trades"]),
        "rejected_capacity_trades": int(summary["rejected_capacity_trades"]),
        "win_rate": float(summary["win_rate"]) if pd.notna(summary["win_rate"]) else np.nan,
        "profit_factor": float(summary["profit_factor"]) if pd.notna(summary["profit_factor"]) else np.nan,
        "realized_pnl_sek": float(summary["total_realized_pnl_sek"]),
        "total_return": float(summary["total_realized_return"]),
        "max_drawdown": float(summary["max_drawdown"]),
        "avg_r_multiple": float(summary["avg_r_multiple"]) if pd.notna(summary["avg_r_multiple"]) else np.nan,
        "pnl_change_vs_baseline_sek": np.nan,
        "retained_pnl_ratio_vs_baseline": np.nan,
        "profitable": bool(float(summary["total_realized_pnl_sek"]) > 0),
        "rank_by_pnl": np.nan,
        "analysis_start_date": analysis_start_date,
        "analysis_end_date": analysis_end_date,
    }



def _safe_series_stat(series: pd.Series, method: str) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float(getattr(clean, method)())

def build_sensitivity(scenarios: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    mappings = {
        "MIN_GAP": "min_gap",
        "MAX_GAP": "max_gap",
        "OPENING_RANGE_MINUTES": "opening_range_minutes",
        "ENTRY_WINDOW_END": "entry_window_end",
        "TARGET_RECOVERY_FRACTION": "target_recovery_fraction",
        "MAX_RISK_PCT": "max_risk_pct",
    }

    core = scenarios[scenarios["scenario_family"] == "CORE_NEIGHBORHOOD"].copy()
    for dimension, column in mappings.items():
        values = core[column].copy()
        if column == "max_risk_pct":
            values = values.fillna("NONE")
        core_dimension = core.assign(_parameter_value=values)
        for value, group in core_dimension.groupby("_parameter_value", dropna=False, sort=True):
            pnl = pd.to_numeric(group["realized_pnl_sek"], errors="coerce")
            retained = pd.to_numeric(group["retained_pnl_ratio_vs_baseline"], errors="coerce")
            rows.append(
                {
                    "validation_suite_version": VALIDATION_SUITE_VERSION,
                    "module_id": MODULE_ID,
                    "dimension": dimension,
                    "parameter_value": str(value),
                    "scenario_count": int(len(group)),
                    "profitable_scenario_count": int(group["profitable"].fillna(False).astype(bool).sum()),
                    "profitable_scenario_share": float(group["profitable"].fillna(False).astype(bool).mean()),
                    "median_realized_pnl_sek": float(pnl.median()),
                    "mean_realized_pnl_sek": float(pnl.mean()),
                    "min_realized_pnl_sek": float(pnl.min()),
                    "max_realized_pnl_sek": float(pnl.max()),
                    "median_retained_pnl_ratio": float(retained.median()),
                    "median_selected_closed_trades": float(pd.to_numeric(group["selected_closed_trades"], errors="coerce").median()),
                    "median_profit_factor": _safe_series_stat(group["profit_factor"], "median"),
                    "median_max_drawdown": _safe_series_stat(group["max_drawdown"], "median"),
                }
            )

    return pd.DataFrame(rows, columns=SENSITIVITY_COLUMNS)


def classify_robustness(core: pd.DataFrame, oat: pd.DataFrame) -> str:
    if core.empty:
        return "INSUFFICIENT_SCENARIOS"
    core_share = float(core["profitable"].fillna(False).astype(bool).mean())
    oat_share = float(oat["profitable"].fillna(False).astype(bool).mean()) if not oat.empty else np.nan
    p25 = float(pd.to_numeric(core["realized_pnl_sek"], errors="coerce").quantile(0.25))
    if core_share >= 0.90 and oat_share >= 0.90 and p25 > 0:
        return "ROBUST_POSITIVE_NEIGHBORHOOD"
    if core_share >= 0.70 and p25 > 0:
        return "MODERATELY_ROBUST_POSITIVE"
    if core_share >= 0.50:
        return "MIXED_PARAMETER_SENSITIVITY"
    return "FRAGILE_PARAMETER_REGION"


def build_outputs(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    reconciliation = build_session_reconciliation(prices)
    complete_dates = completed_dates_from_reconciliation(reconciliation)
    if not complete_dates:
        empty_summary = pd.DataFrame(columns=SUMMARY_COLUMNS)
        return empty_summary, pd.DataFrame(columns=SCENARIO_COLUMNS), pd.DataFrame(columns=SENSITIVITY_COLUMNS), reconciliation

    analysis_start_date = min(complete_dates).isoformat()
    analysis_end_date = max(complete_dates).isoformat()
    sessions = _prepare_sessions(prices, complete_dates)
    daily_reference = build_daily_reference(prices)
    early_regime = calculate_early_market_regime(prices, daily_reference)

    rows: list[dict] = []
    for scenario in generate_scenarios():
        trades, candidate_count, valid_setup_count = _build_parameter_trades(
            scenario=scenario,
            sessions=sessions,
            daily_reference=daily_reference,
            early_regime=early_regime,
        )
        rows.append(
            _scenario_row(
                scenario,
                trades,
                candidate_count,
                valid_setup_count,
                analysis_start_date,
                analysis_end_date,
            )
        )

    scenarios = pd.DataFrame(rows, columns=SCENARIO_COLUMNS)
    baseline_pnl = float(scenarios.loc[scenarios["scenario_id"] == "V1_BASELINE", "realized_pnl_sek"].iloc[0])
    scenarios["pnl_change_vs_baseline_sek"] = scenarios["realized_pnl_sek"] - baseline_pnl
    scenarios["retained_pnl_ratio_vs_baseline"] = np.where(
        baseline_pnl != 0,
        scenarios["realized_pnl_sek"] / baseline_pnl,
        np.nan,
    )
    scenarios["rank_by_pnl"] = scenarios["realized_pnl_sek"].rank(method="min", ascending=False).astype(int)

    baseline = scenarios[scenarios["scenario_id"] == "V1_BASELINE"].iloc[0]
    oat = scenarios[scenarios["scenario_family"] == "ONE_AT_A_TIME"].copy()
    core = scenarios[scenarios["scenario_family"] == "CORE_NEIGHBORHOOD"].copy()
    best = scenarios.sort_values(["realized_pnl_sek", "scenario_id"], ascending=[False, True]).iloc[0]
    worst = scenarios.sort_values(["realized_pnl_sek", "scenario_id"], ascending=[True, True]).iloc[0]
    complete_rows = reconciliation[reconciliation["included_in_parameter_analysis"].fillna(False)]
    incomplete_rows = reconciliation[~reconciliation["included_in_parameter_analysis"].fillna(False)]

    summary_row = {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "module_id": MODULE_ID,
        "strategy_id": STRATEGY_ID,
        "research_status": RESEARCH_STATUS,
        "analysis_mode": ANALYSIS_MODE,
        "regime_policy": REGIME_POLICY,
        "execution_policy": EXECUTION_POLICY,
        "analysis_start_date": analysis_start_date,
        "analysis_end_date": analysis_end_date,
        "complete_session_dates": int(len(complete_rows)),
        "excluded_incomplete_dates": int(len(incomplete_rows)),
        "baseline_scenario_id": "V1_BASELINE",
        "baseline_candidate_count": int(baseline["candidate_count"]),
        "baseline_triggered_trades": int(baseline["triggered_trade_count"]),
        "baseline_selected_closed_trades": int(baseline["selected_closed_trades"]),
        "baseline_rejected_capacity_trades": int(baseline["rejected_capacity_trades"]),
        "baseline_realized_pnl_sek": float(baseline["realized_pnl_sek"]),
        "baseline_profit_factor": float(baseline["profit_factor"]),
        "baseline_max_drawdown": float(baseline["max_drawdown"]),
        "scenario_count": int(len(scenarios)),
        "profitable_scenario_count": int(scenarios["profitable"].sum()),
        "profitable_scenario_share": float(scenarios["profitable"].mean()),
        "one_at_a_time_scenario_count": int(len(oat)),
        "one_at_a_time_profitable_count": int(oat["profitable"].sum()),
        "one_at_a_time_profitable_share": float(oat["profitable"].mean()),
        "core_neighborhood_scenario_count": int(len(core)),
        "core_neighborhood_profitable_count": int(core["profitable"].sum()),
        "core_neighborhood_profitable_share": float(core["profitable"].mean()),
        "core_neighborhood_median_pnl_sek": float(core["realized_pnl_sek"].median()),
        "core_neighborhood_p25_pnl_sek": float(core["realized_pnl_sek"].quantile(0.25)),
        "core_neighborhood_min_pnl_sek": float(core["realized_pnl_sek"].min()),
        "core_neighborhood_max_pnl_sek": float(core["realized_pnl_sek"].max()),
        "core_neighborhood_median_retained_pnl_ratio": float(core["retained_pnl_ratio_vs_baseline"].median()),
        "best_scenario_id": str(best["scenario_id"]),
        "best_scenario_pnl_sek": float(best["realized_pnl_sek"]),
        "worst_scenario_id": str(worst["scenario_id"]),
        "worst_scenario_pnl_sek": float(worst["realized_pnl_sek"]),
        "baseline_rank_by_pnl": int(baseline["rank_by_pnl"]),
        "baseline_percentile_by_pnl": float((scenarios["realized_pnl_sek"] <= baseline_pnl).mean()),
        "robustness_classification": classify_robustness(core, oat),
    }
    summary = pd.DataFrame([summary_row], columns=SUMMARY_COLUMNS)
    sensitivity = build_sensitivity(scenarios)
    return summary, scenarios, sensitivity, reconciliation


def export_outputs(
    summary: pd.DataFrame,
    scenarios: pd.DataFrame,
    sensitivity: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> None:
    outputs = {
        SUMMARY_FILE: summary,
        SCENARIOS_FILE: scenarios,
        SENSITIVITY_FILE: sensitivity,
        RECONCILIATION_FILE: reconciliation,
    }
    for path, frame in outputs.items():
        export_csv_for_power_bi(frame, path)
        print(f"Saved {path.name}: {len(frame)} rows")


def main() -> None:
    print("\n=== V1 RESEARCH VALIDATION SUITE - STEP 4 ===")
    print("Module          : Parameter robustness grid")
    print(f"Strategy        : {STRATEGY_ID}")
    print(f"Analysis mode   : {ANALYSIS_MODE}")
    print(f"Regime policy   : {REGIME_POLICY}")
    print("Scenario design : baseline + one-at-a-time + 216 core-neighborhood combinations")
    print("V1 production/research rules and existing output files are not changed.")

    prices = load_intraday_prices()
    summary, scenarios, sensitivity, reconciliation = build_outputs(prices)
    export_outputs(summary, scenarios, sensitivity, reconciliation)

    if summary.empty:
        print("No complete sessions were available for parameter robustness analysis.")
        return

    row = summary.iloc[0]
    print("\n=== PARAMETER ROBUSTNESS RESULT ===")
    print(f"Completed sessions          : {int(row['complete_session_dates'])}")
    print(f"Excluded incomplete dates   : {int(row['excluded_incomplete_dates'])}")
    print(f"Baseline completed PnL      : {float(row['baseline_realized_pnl_sek']):.2f} SEK")
    print(f"Scenarios tested            : {int(row['scenario_count'])}")
    print(
        "Profitable all scenarios   : "
        f"{int(row['profitable_scenario_count'])}/{int(row['scenario_count'])}"
    )
    print(
        "Profitable OAT scenarios   : "
        f"{int(row['one_at_a_time_profitable_count'])}/{int(row['one_at_a_time_scenario_count'])}"
    )
    print(
        "Profitable core grid       : "
        f"{int(row['core_neighborhood_profitable_count'])}/{int(row['core_neighborhood_scenario_count'])}"
    )
    print(f"Core-grid median PnL        : {float(row['core_neighborhood_median_pnl_sek']):.2f} SEK")
    print(f"Core-grid 25th pct PnL      : {float(row['core_neighborhood_p25_pnl_sek']):.2f} SEK")
    print(
        f"Worst scenario             : {row['worst_scenario_id']} -> "
        f"{float(row['worst_scenario_pnl_sek']):.2f} SEK"
    )
    print(f"Classification              : {row['robustness_classification']}")
    print("Step 4 validation export complete.")


if __name__ == "__main__":
    main()
