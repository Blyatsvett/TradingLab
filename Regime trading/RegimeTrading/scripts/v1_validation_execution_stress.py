from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.core.research_config import ORB_COST_PER_TRADE
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    RESEARCH_STATUS,
    STRATEGY_ID,
)
from RegimeTrading.scripts.v1_validation_portfolio import (
    PORTFOLIO_MODEL_ID,
    POSITION_SIZE_SEK,
    load_source_trades,
    simulate_portfolio,
)


VALIDATION_SUITE_VERSION = "V1_RESEARCH_VALIDATION_SUITE_STEP3"
ANALYSIS_ID = "EXECUTION_AND_COST_STRESS_TEST_V1"
BASELINE_TOTAL_COST_BPS = float(ORB_COST_PER_TRADE) * 10000.0
MARKET_LIKE_EXIT_REASONS = frozenset({"STOP_HIT", "CLOSED_EOD"})
TARGET_LIMIT_EXIT_REASONS = frozenset({"TARGET_HIT"})

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
SUMMARY_FILE = OUTPUT_DIR / "v1_validation_execution_stress_summary.csv"
SCENARIOS_FILE = OUTPUT_DIR / "v1_validation_execution_stress_scenarios.csv"
TRADE_DETAIL_FILE = OUTPUT_DIR / "v1_validation_execution_stress_trade_detail.csv"
COST_CURVE_FILE = OUTPUT_DIR / "v1_validation_execution_cost_curve.csv"

SUMMARY_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "research_status",
    "portfolio_model_id",
    "baseline_total_cost_bps",
    "baseline_realized_pnl_sek",
    "baseline_selected_closed_trades",
    "baseline_profit_factor",
    "baseline_max_drawdown",
    "zero_cost_realized_pnl_sek",
    "gross_edge_before_costs_sek",
    "break_even_total_cost_bps",
    "highest_tested_profitable_cost_bps",
    "moderate_stress_pnl_sek",
    "moderate_stress_retained_pnl_ratio",
    "conservative_stress_pnl_sek",
    "conservative_stress_retained_pnl_ratio",
    "harsh_stress_pnl_sek",
    "harsh_stress_retained_pnl_ratio",
    "scenario_count",
    "profitable_scenario_count",
    "worst_scenario_id",
    "worst_scenario_label",
    "worst_scenario_pnl_sek",
    "all_predefined_scenarios_profitable",
]

SCENARIO_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "portfolio_model_id",
    "scenario_order",
    "scenario_id",
    "scenario_label",
    "scenario_category",
    "total_cost_bps",
    "entry_slippage_bps",
    "market_exit_slippage_bps",
    "target_exit_slippage_bps",
    "selected_closed_trades",
    "selected_open_trades",
    "rejected_capacity_trades",
    "win_rate",
    "gross_profit_sek",
    "gross_loss_sek",
    "profit_factor",
    "realized_pnl_sek",
    "final_realized_equity_sek",
    "total_realized_return",
    "max_drawdown",
    "pnl_change_vs_baseline_sek",
    "retained_pnl_ratio",
    "remains_profitable",
]

TRADE_DETAIL_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "portfolio_model_id",
    "scenario_id",
    "scenario_label",
    "scenario_category",
    "source_trade_row",
    "date",
    "ticker",
    "entry_time",
    "exit_time",
    "exit_reason",
    "selected_for_portfolio",
    "selection_status",
    "source_entry_price",
    "source_exit_price",
    "stressed_entry_price",
    "stressed_exit_price",
    "source_net_pnl_pct",
    "reconstructed_source_gross_pnl_pct",
    "stressed_gross_pnl_pct",
    "stressed_net_pnl_pct",
    "net_pnl_change_pct",
    "total_cost_bps",
    "entry_slippage_bps",
    "applied_exit_slippage_bps",
    "market_exit_slippage_bps",
    "target_exit_slippage_bps",
    "stressed_portfolio_pnl_sek",
]

COST_CURVE_COLUMNS = [
    "validation_suite_version",
    "analysis_id",
    "strategy_id",
    "portfolio_model_id",
    "total_cost_bps",
    "selected_closed_trades",
    "realized_pnl_sek",
    "final_realized_equity_sek",
    "retained_pnl_ratio_vs_baseline",
    "remains_profitable",
]


@dataclass(frozen=True)
class StressScenario:
    order: int
    scenario_id: str
    label: str
    category: str
    total_cost_bps: float
    entry_slippage_bps: float = 0.0
    market_exit_slippage_bps: float = 0.0
    target_exit_slippage_bps: float = 0.0


@dataclass
class ValidationStep3Result:
    summary: pd.DataFrame
    scenarios: pd.DataFrame
    trade_detail: pd.DataFrame
    cost_curve: pd.DataFrame


def predefined_scenarios() -> list[StressScenario]:
    return [
        StressScenario(1, "BASELINE", "Baseline V1 assumptions", "BASELINE", 5.0),
        StressScenario(2, "ZERO_COST", "Zero transaction cost", "COST_ONLY", 0.0),
        StressScenario(3, "COST_2_5_BPS", "Total cost 2.5 bps", "COST_ONLY", 2.5),
        StressScenario(4, "COST_7_5_BPS", "Total cost 7.5 bps", "COST_ONLY", 7.5),
        StressScenario(5, "COST_10_BPS", "Total cost 10 bps", "COST_ONLY", 10.0),
        StressScenario(6, "COST_15_BPS", "Total cost 15 bps", "COST_ONLY", 15.0),
        StressScenario(7, "ENTRY_1_BPS", "Adverse entry slippage 1 bp", "ENTRY_SLIPPAGE", 5.0, 1.0),
        StressScenario(8, "ENTRY_2_BPS", "Adverse entry slippage 2 bps", "ENTRY_SLIPPAGE", 5.0, 2.0),
        StressScenario(9, "ENTRY_5_BPS", "Adverse entry slippage 5 bps", "ENTRY_SLIPPAGE", 5.0, 5.0),
        StressScenario(10, "MARKET_EXIT_1_BPS", "Stop/EOD exit slippage 1 bp", "EXIT_SLIPPAGE", 5.0, 0.0, 1.0),
        StressScenario(11, "MARKET_EXIT_2_BPS", "Stop/EOD exit slippage 2 bps", "EXIT_SLIPPAGE", 5.0, 0.0, 2.0),
        StressScenario(12, "MARKET_EXIT_5_BPS", "Stop/EOD exit slippage 5 bps", "EXIT_SLIPPAGE", 5.0, 0.0, 5.0),
        StressScenario(13, "MODERATE", "Moderate: 7.5 cost + 1 entry + 1 market exit bp", "COMBINED", 7.5, 1.0, 1.0),
        StressScenario(14, "CONSERVATIVE", "Conservative: 10 cost + 2 entry + 2 market exit bps", "COMBINED", 10.0, 2.0, 2.0),
        StressScenario(15, "HARSH", "Harsh: 15 cost + 5 entry + 5 market exit bps", "COMBINED", 15.0, 5.0, 5.0),
    ]


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or pd.isna(denominator):
        return np.nan
    return float(numerator) / float(denominator)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _applied_exit_slippage(exit_reason: str, scenario: StressScenario) -> float:
    reason = str(exit_reason or "").strip().upper()
    if reason in MARKET_LIKE_EXIT_REASONS:
        return float(scenario.market_exit_slippage_bps)
    if reason in TARGET_LIMIT_EXIT_REASONS:
        return float(scenario.target_exit_slippage_bps)
    return 0.0


def stress_trade_returns(
    trades: pd.DataFrame,
    scenario: StressScenario,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a stressed trade frame plus calculation detail.

    The source V1 trade rows and timestamps are unchanged. Closed-trade returns are
    recalculated from source entry/exit prices after adverse price adjustments and
    the scenario's total round-trip cost. Open trades retain zero realized return.
    """
    work = trades.copy().reset_index(drop=True)
    if "source_trade_row" not in work.columns:
        work["source_trade_row"] = work.index.astype(int)

    for column in ["entry_price", "exit_price", "pnl_pct"]:
        if column not in work.columns:
            work[column] = np.nan
        work[column] = _numeric(work[column])

    for column in ["date", "ticker", "entry_time", "exit_time", "exit_reason"]:
        if column not in work.columns:
            work[column] = ""
        work[column] = work[column].fillna("").astype(str)

    is_closed = work["exit_reason"].str.strip().ne("") & work["exit_price"].notna()
    entry_multiplier = 1.0 + float(scenario.entry_slippage_bps) / 10000.0

    work["stressed_entry_price"] = work["entry_price"]
    work.loc[is_closed, "stressed_entry_price"] = (
        work.loc[is_closed, "entry_price"] * entry_multiplier
    )

    applied_exit = work["exit_reason"].map(
        lambda reason: _applied_exit_slippage(reason, scenario)
    )
    work["applied_exit_slippage_bps"] = applied_exit
    work["stressed_exit_price"] = work["exit_price"]
    work.loc[is_closed, "stressed_exit_price"] = work.loc[is_closed, "exit_price"] * (
        1.0 - applied_exit.loc[is_closed] / 10000.0
    )

    source_gross = pd.Series(np.nan, index=work.index, dtype=float)
    source_gross.loc[is_closed] = (
        work.loc[is_closed, "exit_price"] / work.loc[is_closed, "entry_price"] - 1.0
    )
    stressed_gross = pd.Series(np.nan, index=work.index, dtype=float)
    stressed_gross.loc[is_closed] = (
        work.loc[is_closed, "stressed_exit_price"]
        / work.loc[is_closed, "stressed_entry_price"]
        - 1.0
    )
    stressed_net = pd.Series(0.0, index=work.index, dtype=float)
    stressed_net.loc[is_closed] = (
        stressed_gross.loc[is_closed] - float(scenario.total_cost_bps) / 10000.0
    )

    work["reconstructed_source_gross_pnl_pct"] = source_gross
    work["stressed_gross_pnl_pct"] = stressed_gross
    work["stressed_net_pnl_pct"] = stressed_net
    work["source_net_pnl_pct_original"] = work["pnl_pct"]
    work["net_pnl_change_pct"] = stressed_net - work["pnl_pct"].fillna(0.0)
    work["pnl_pct"] = stressed_net
    work["pnl_sek"] = float(POSITION_SIZE_SEK) * stressed_net

    detail = work[
        [
            "source_trade_row",
            "date",
            "ticker",
            "entry_time",
            "exit_time",
            "exit_reason",
            "entry_price",
            "exit_price",
            "stressed_entry_price",
            "stressed_exit_price",
            "source_net_pnl_pct_original",
            "reconstructed_source_gross_pnl_pct",
            "stressed_gross_pnl_pct",
            "stressed_net_pnl_pct",
            "net_pnl_change_pct",
            "applied_exit_slippage_bps",
        ]
    ].copy()
    detail = detail.rename(
        columns={
            "entry_price": "source_entry_price",
            "exit_price": "source_exit_price",
            "source_net_pnl_pct_original": "source_net_pnl_pct",
        }
    )
    detail["total_cost_bps"] = float(scenario.total_cost_bps)
    detail["entry_slippage_bps"] = float(scenario.entry_slippage_bps)
    detail["market_exit_slippage_bps"] = float(scenario.market_exit_slippage_bps)
    detail["target_exit_slippage_bps"] = float(scenario.target_exit_slippage_bps)

    return work, detail


def run_scenario(
    trades: pd.DataFrame,
    scenario: StressScenario,
):
    stressed_trades, calc_detail = stress_trade_returns(trades, scenario)
    portfolio = simulate_portfolio(stressed_trades)
    return portfolio, calc_detail


def _scenario_row(
    scenario: StressScenario,
    portfolio,
    baseline_pnl: float,
) -> dict:
    row = portfolio.summary.iloc[0]
    pnl = float(row["total_realized_pnl_sek"])
    return {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "analysis_id": ANALYSIS_ID,
        "strategy_id": STRATEGY_ID,
        "portfolio_model_id": PORTFOLIO_MODEL_ID,
        "scenario_order": int(scenario.order),
        "scenario_id": scenario.scenario_id,
        "scenario_label": scenario.label,
        "scenario_category": scenario.category,
        "total_cost_bps": float(scenario.total_cost_bps),
        "entry_slippage_bps": float(scenario.entry_slippage_bps),
        "market_exit_slippage_bps": float(scenario.market_exit_slippage_bps),
        "target_exit_slippage_bps": float(scenario.target_exit_slippage_bps),
        "selected_closed_trades": int(row["selected_closed_trades"]),
        "selected_open_trades": int(row["selected_open_trades"]),
        "rejected_capacity_trades": int(row["rejected_capacity_trades"]),
        "win_rate": float(row["win_rate"]) if pd.notna(row["win_rate"]) else np.nan,
        "gross_profit_sek": float(row["gross_profit_sek"]),
        "gross_loss_sek": float(row["gross_loss_sek"]),
        "profit_factor": float(row["profit_factor"]) if pd.notna(row["profit_factor"]) else np.nan,
        "realized_pnl_sek": pnl,
        "final_realized_equity_sek": float(row["final_realized_equity_sek"]),
        "total_realized_return": float(row["total_realized_return"]),
        "max_drawdown": float(row["max_drawdown"]),
        "pnl_change_vs_baseline_sek": pnl - baseline_pnl,
        "retained_pnl_ratio": _safe_ratio(pnl, baseline_pnl),
        "remains_profitable": pnl > 0.0,
    }


def _detail_rows(
    scenario: StressScenario,
    calc_detail: pd.DataFrame,
    portfolio,
) -> pd.DataFrame:
    ledger = portfolio.ledger[
        [
            "source_trade_row",
            "selected_for_portfolio",
            "selection_status",
            "portfolio_pnl_sek",
        ]
    ].copy()
    ledger = ledger.rename(columns={"portfolio_pnl_sek": "stressed_portfolio_pnl_sek"})
    detail = calc_detail.merge(ledger, on="source_trade_row", how="left")
    detail["validation_suite_version"] = VALIDATION_SUITE_VERSION
    detail["analysis_id"] = ANALYSIS_ID
    detail["strategy_id"] = STRATEGY_ID
    detail["portfolio_model_id"] = PORTFOLIO_MODEL_ID
    detail["scenario_id"] = scenario.scenario_id
    detail["scenario_label"] = scenario.label
    detail["scenario_category"] = scenario.category
    return detail[TRADE_DETAIL_COLUMNS]


def build_cost_curve(
    trades: pd.DataFrame,
    baseline_pnl: float,
    start_bps: float = 0.0,
    end_bps: float = 40.0,
    step_bps: float = 0.5,
) -> pd.DataFrame:
    levels = np.arange(start_bps, end_bps + step_bps / 2.0, step_bps)
    rows: list[dict] = []
    for idx, cost_bps in enumerate(levels, start=1):
        scenario = StressScenario(
            order=idx,
            scenario_id=f"COST_CURVE_{cost_bps:.1f}",
            label=f"Total cost {cost_bps:.1f} bps",
            category="COST_CURVE",
            total_cost_bps=float(cost_bps),
        )
        portfolio, _ = run_scenario(trades, scenario)
        summary = portfolio.summary.iloc[0]
        pnl = float(summary["total_realized_pnl_sek"])
        rows.append(
            {
                "validation_suite_version": VALIDATION_SUITE_VERSION,
                "analysis_id": ANALYSIS_ID,
                "strategy_id": STRATEGY_ID,
                "portfolio_model_id": PORTFOLIO_MODEL_ID,
                "total_cost_bps": float(cost_bps),
                "selected_closed_trades": int(summary["selected_closed_trades"]),
                "realized_pnl_sek": pnl,
                "final_realized_equity_sek": float(summary["final_realized_equity_sek"]),
                "retained_pnl_ratio_vs_baseline": _safe_ratio(pnl, baseline_pnl),
                "remains_profitable": pnl > 0.0,
            }
        )
    return pd.DataFrame(rows, columns=COST_CURVE_COLUMNS)


def _scenario_value(scenarios: pd.DataFrame, scenario_id: str, column: str) -> float:
    match = scenarios[scenarios["scenario_id"] == scenario_id]
    if match.empty:
        return np.nan
    return float(match.iloc[0][column])


def _break_even_cost_bps(cost_curve: pd.DataFrame) -> float:
    if cost_curve.empty:
        return np.nan
    curve = cost_curve.sort_values("total_cost_bps").reset_index(drop=True)
    positive = curve[curve["realized_pnl_sek"] > 0]
    nonpositive = curve[curve["realized_pnl_sek"] <= 0]
    if positive.empty:
        return 0.0
    if nonpositive.empty:
        return np.nan

    low = positive.iloc[-1]
    high_candidates = nonpositive[nonpositive["total_cost_bps"] > low["total_cost_bps"]]
    if high_candidates.empty:
        return float(low["total_cost_bps"])
    high = high_candidates.iloc[0]
    x0 = float(low["total_cost_bps"])
    y0 = float(low["realized_pnl_sek"])
    x1 = float(high["total_cost_bps"])
    y1 = float(high["realized_pnl_sek"])
    if y1 == y0:
        return x0
    return x0 + (0.0 - y0) * (x1 - x0) / (y1 - y0)


def build_validation_step3(trades: pd.DataFrame) -> ValidationStep3Result:
    scenario_defs = predefined_scenarios()

    baseline_portfolio, baseline_calc = run_scenario(trades, scenario_defs[0])
    baseline_row = baseline_portfolio.summary.iloc[0]
    baseline_pnl = float(baseline_row["total_realized_pnl_sek"])

    scenario_rows: list[dict] = []
    detail_frames: list[pd.DataFrame] = []
    for scenario in scenario_defs:
        if scenario.scenario_id == "BASELINE":
            portfolio = baseline_portfolio
            calc_detail = baseline_calc
        else:
            portfolio, calc_detail = run_scenario(trades, scenario)
        scenario_rows.append(_scenario_row(scenario, portfolio, baseline_pnl))
        detail_frames.append(_detail_rows(scenario, calc_detail, portfolio))

    scenarios = pd.DataFrame(scenario_rows, columns=SCENARIO_COLUMNS)
    trade_detail = pd.concat(detail_frames, ignore_index=True)[TRADE_DETAIL_COLUMNS]
    cost_curve = build_cost_curve(trades, baseline_pnl)

    positive_costs = cost_curve[cost_curve["remains_profitable"]]
    highest_profitable_cost = (
        float(positive_costs["total_cost_bps"].max()) if not positive_costs.empty else np.nan
    )
    break_even_cost = _break_even_cost_bps(cost_curve)
    worst = scenarios.sort_values(["realized_pnl_sek", "scenario_order"]).iloc[0]

    moderate_pnl = _scenario_value(scenarios, "MODERATE", "realized_pnl_sek")
    conservative_pnl = _scenario_value(scenarios, "CONSERVATIVE", "realized_pnl_sek")
    harsh_pnl = _scenario_value(scenarios, "HARSH", "realized_pnl_sek")
    zero_cost_pnl = _scenario_value(scenarios, "ZERO_COST", "realized_pnl_sek")

    summary_row = {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "analysis_id": ANALYSIS_ID,
        "strategy_id": STRATEGY_ID,
        "research_status": RESEARCH_STATUS,
        "portfolio_model_id": PORTFOLIO_MODEL_ID,
        "baseline_total_cost_bps": BASELINE_TOTAL_COST_BPS,
        "baseline_realized_pnl_sek": baseline_pnl,
        "baseline_selected_closed_trades": int(baseline_row["selected_closed_trades"]),
        "baseline_profit_factor": float(baseline_row["profit_factor"]) if pd.notna(baseline_row["profit_factor"]) else np.nan,
        "baseline_max_drawdown": float(baseline_row["max_drawdown"]),
        "zero_cost_realized_pnl_sek": zero_cost_pnl,
        "gross_edge_before_costs_sek": zero_cost_pnl,
        "break_even_total_cost_bps": break_even_cost,
        "highest_tested_profitable_cost_bps": highest_profitable_cost,
        "moderate_stress_pnl_sek": moderate_pnl,
        "moderate_stress_retained_pnl_ratio": _safe_ratio(moderate_pnl, baseline_pnl),
        "conservative_stress_pnl_sek": conservative_pnl,
        "conservative_stress_retained_pnl_ratio": _safe_ratio(conservative_pnl, baseline_pnl),
        "harsh_stress_pnl_sek": harsh_pnl,
        "harsh_stress_retained_pnl_ratio": _safe_ratio(harsh_pnl, baseline_pnl),
        "scenario_count": int(len(scenarios)),
        "profitable_scenario_count": int(scenarios["remains_profitable"].sum()),
        "worst_scenario_id": str(worst["scenario_id"]),
        "worst_scenario_label": str(worst["scenario_label"]),
        "worst_scenario_pnl_sek": float(worst["realized_pnl_sek"]),
        "all_predefined_scenarios_profitable": bool(scenarios["remains_profitable"].all()),
    }
    summary = pd.DataFrame([summary_row], columns=SUMMARY_COLUMNS)

    return ValidationStep3Result(
        summary=summary,
        scenarios=scenarios,
        trade_detail=trade_detail,
        cost_curve=cost_curve,
    )


def export_result(result: ValidationStep3Result) -> None:
    outputs = {
        SUMMARY_FILE: result.summary,
        SCENARIOS_FILE: result.scenarios,
        TRADE_DETAIL_FILE: result.trade_detail,
        COST_CURVE_FILE: result.cost_curve,
    }
    for path, frame in outputs.items():
        export_csv_for_power_bi(frame, path)
        print(f"Saved {path.name}: {len(frame)} rows")


def main() -> None:
    print("\n=== V1 RESEARCH VALIDATION SUITE - STEP 3 ===")
    print("Module          : Execution and cost stress testing")
    print(f"Strategy        : {STRATEGY_ID}")
    print(f"Portfolio model : {PORTFOLIO_MODEL_ID}")
    print(f"Baseline cost   : {BASELINE_TOTAL_COST_BPS:.2f} bps total per completed trade")
    print("Entry stress    : adverse percentage-price slippage")
    print("Exit stress     : adverse only for STOP_HIT and CLOSED_EOD")
    print("Target fills    : target-limit price unless explicitly stressed")
    print("V1 trade selection logic, timestamps, stops, targets, and capacity rules are unchanged.")

    trades = load_source_trades()
    result = build_validation_step3(trades)
    export_result(result)

    row = result.summary.iloc[0]
    print("\n=== EXECUTION STRESS RESULT ===")
    print(f"Baseline realized PnL       : {float(row['baseline_realized_pnl_sek']):.2f} SEK")
    print(f"Zero-cost gross edge        : {float(row['zero_cost_realized_pnl_sek']):.2f} SEK")
    print(f"Break-even total cost       : {float(row['break_even_total_cost_bps']):.2f} bps")
    print(f"Moderate stress PnL         : {float(row['moderate_stress_pnl_sek']):.2f} SEK")
    print(f"Conservative stress PnL     : {float(row['conservative_stress_pnl_sek']):.2f} SEK")
    print(f"Harsh stress PnL            : {float(row['harsh_stress_pnl_sek']):.2f} SEK")
    print(
        "Profitable predefined cases : "
        f"{int(row['profitable_scenario_count'])}/{int(row['scenario_count'])}"
    )
    print(
        "Worst predefined case       : "
        f"{row['worst_scenario_id']} -> {float(row['worst_scenario_pnl_sek']):.2f} SEK"
    )
    print("Step 3 validation export complete.")


if __name__ == "__main__":
    main()
