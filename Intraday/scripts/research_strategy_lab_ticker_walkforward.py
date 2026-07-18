from __future__ import annotations

import math

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.market_regime import calculate_daily_market_regime
from Intraday.core.orb_config import (
    ORB_INITIAL_CAPITAL,
    ORB_POSITION_SIZE,
)
from Intraday.core.orb_research import load_normalised_intraday_prices
from Intraday.core.paths import DATA_DIR
from Intraday.scripts.research_strategy_lab_ticker_optimization import (
    STRATEGIES,
    build_all_strategy_candidates,
    build_basket_optimization,
    build_optimization_summary,
    build_ticker_performance,
    discover_downloaded_tickers,
    select_trades_for_strategy_basket,
    summarize_strategy_basket,
    build_equity_curve_for_run,
)


OUTPUT_PERIODS_FILE = DATA_DIR / "strategy_lab_ticker_walkforward_periods.csv"
OUTPUT_RESULTS_FILE = DATA_DIR / "strategy_lab_ticker_walkforward_results.csv"
OUTPUT_SUMMARY_FILE = DATA_DIR / "strategy_lab_ticker_walkforward_summary.csv"
OUTPUT_TRADES_FILE = DATA_DIR / "strategy_lab_ticker_walkforward_trades.csv"
OUTPUT_EQUITY_FILE = DATA_DIR / "strategy_lab_ticker_walkforward_equity_curve.csv"
OUTPUT_TRAIN_CHOICES_FILE = DATA_DIR / "strategy_lab_ticker_walkforward_train_choices.csv"


TRAIN_WINDOW_DAYS = 30
TEST_WINDOW_DAYS = 10
STEP_DAYS = 10

MIN_TOTAL_TEST_TRADES = 20
MIN_POSITIVE_TEST_PERIOD_SHARE = 0.60


def normalise_dates(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    output = output.dropna(subset=["date"])
    return output


def parse_ticker_string(value: str) -> list[str]:
    return [
        ticker.strip()
        for ticker in str(value).split(",")
        if ticker.strip()
    ]


def build_walkforward_periods(unique_dates: list[str]) -> pd.DataFrame:
    rows = []

    max_start = len(unique_dates) - TRAIN_WINDOW_DAYS - TEST_WINDOW_DAYS

    if max_start < 0:
        return pd.DataFrame()

    period_number = 0

    for start_idx in range(0, max_start + 1, STEP_DAYS):
        period_number += 1

        train_dates = unique_dates[start_idx:start_idx + TRAIN_WINDOW_DAYS]
        test_dates = unique_dates[
            start_idx + TRAIN_WINDOW_DAYS:
            start_idx + TRAIN_WINDOW_DAYS + TEST_WINDOW_DAYS
        ]

        rows.append(
            {
                "period_id": f"P{period_number:02d}",
                "train_start_date": train_dates[0],
                "train_end_date": train_dates[-1],
                "test_start_date": test_dates[0],
                "test_end_date": test_dates[-1],
                "train_days": len(train_dates),
                "test_days": len(test_dates),
                "train_dates": ",".join(train_dates),
                "test_dates": ",".join(test_dates),
            }
        )

    return pd.DataFrame(rows)


def filter_candidates_by_dates(
    candidates: pd.DataFrame,
    dates: list[str],
) -> pd.DataFrame:
    return candidates[candidates["date"].isin(dates)].copy()


def prefix_summary(summary: dict, prefix: str) -> dict:
    fields = [
        "candidate_trades",
        "selected_trades",
        "active_days",
        "first_date",
        "last_date",
        "final_equity",
        "total_return",
        "total_pnl_sek",
        "win_rate",
        "avg_trade",
        "median_trade",
        "best_trade",
        "worst_trade",
        "profit_factor",
        "max_drawdown",
        "avg_risk_pct",
        "max_risk_pct",
        "target_count",
        "stop_count",
        "close_count",
        "meets_min_trades",
        "meets_min_active_days",
        "research_candidate",
    ]

    return {
        f"{prefix}_{field}": summary.get(field, 0)
        for field in fields
    }


def evaluate_strategy_basket(
    candidates: pd.DataFrame,
    strategy_name: str,
    summary_role: str,
    basket_tickers: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    selected = select_trades_for_strategy_basket(
        candidates=candidates,
        strategy_name=strategy_name,
        basket_type=summary_role,
        tickers=basket_tickers,
    )

    summary = summarize_strategy_basket(
        selected_trades=selected,
        candidates=candidates,
        strategy_name=strategy_name,
        basket_type=summary_role,
        tickers=basket_tickers,
    )

    equity = build_equity_curve_for_run(
        selected_trades=selected,
        strategy_name=strategy_name,
        basket_type=summary_role,
        tickers=basket_tickers,
    )

    return selected, equity, summary


def add_walkforward_metadata(
    df: pd.DataFrame,
    period: pd.Series,
    strategy_name: str,
    summary_role: str,
    trained_basket_type: str,
    basket_tickers: list[str],
    evaluation_phase: str,
) -> pd.DataFrame:
    if df.empty:
        return df

    output = df.copy()

    output["period_id"] = period["period_id"]
    output["train_start_date"] = period["train_start_date"]
    output["train_end_date"] = period["train_end_date"]
    output["test_start_date"] = period["test_start_date"]
    output["test_end_date"] = period["test_end_date"]
    output["summary_role"] = summary_role
    output["trained_basket_type"] = trained_basket_type
    output["basket_tickers"] = ", ".join(sorted(basket_tickers))
    output["basket_ticker_count"] = len(basket_tickers)
    output["evaluation_phase"] = evaluation_phase

    output["walkforward_run_id"] = (
        output["period_id"].astype(str)
        + "__"
        + strategy_name
        + "__"
        + summary_role
    )

    return output


def build_baseline_comparison_fields(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return results

    output = results.copy()

    baseline = output[
        output["summary_role"].eq("current_orb_basket")
    ][
        [
            "period_id",
            "strategy_name",
            "test_total_return",
            "test_total_pnl_sek",
            "test_profit_factor",
            "test_max_drawdown",
        ]
    ].copy()

    baseline = baseline.rename(
        columns={
            "test_total_return": "current_orb_basket_test_total_return",
            "test_total_pnl_sek": "current_orb_basket_test_total_pnl_sek",
            "test_profit_factor": "current_orb_basket_test_profit_factor",
            "test_max_drawdown": "current_orb_basket_test_max_drawdown",
        }
    )

    output = output.merge(
        baseline,
        on=["period_id", "strategy_name"],
        how="left",
    )

    output["test_excess_return_vs_current_orb_basket"] = (
        output["test_total_return"]
        - output["current_orb_basket_test_total_return"].fillna(0.0)
    )

    output["test_excess_pnl_vs_current_orb_basket"] = (
        output["test_total_pnl_sek"]
        - output["current_orb_basket_test_total_pnl_sek"].fillna(0.0)
    )

    output["test_beats_current_orb_basket"] = (
        output["test_excess_return_vs_current_orb_basket"] > 0
    )

    return output


def build_walkforward_summary(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame()

    rows = []

    grouped = results.groupby(
        ["strategy_name", "summary_role"],
        dropna=False,
    )

    for (strategy_name, summary_role), group in grouped:
        periods_tested = int(group["period_id"].nunique())
        positive_test_periods = int((group["test_total_return"] > 0).sum())
        negative_test_periods = int((group["test_total_return"] < 0).sum())

        beat_baseline_periods = int(
            group["test_beats_current_orb_basket"].fillna(False).sum()
        )

        total_test_trades = int(group["test_selected_trades"].sum())
        total_test_return = float(group["test_total_return"].sum())
        total_test_pnl_sek = float(group["test_total_pnl_sek"].sum())

        positive_period_share = (
            positive_test_periods / periods_tested
            if periods_tested > 0
            else 0.0
        )

        beat_baseline_share = (
            beat_baseline_periods / periods_tested
            if periods_tested > 0
            else 0.0
        )

        required_positive_periods = math.ceil(
            periods_tested * MIN_POSITIVE_TEST_PERIOD_SHARE
        )

        walkforward_candidate = (
            periods_tested > 0
            and total_test_trades >= MIN_TOTAL_TEST_TRADES
            and total_test_return > 0
            and positive_test_periods >= required_positive_periods
            and float(group["test_profit_factor"].replace(999.0, pd.NA).dropna().mean() or 0.0) > 1.0
        )

        rows.append(
            {
                "strategy_name": strategy_name,
                "summary_role": summary_role,
                "periods_tested": periods_tested,
                "positive_test_periods": positive_test_periods,
                "negative_test_periods": negative_test_periods,
                "positive_period_share": positive_period_share,
                "beat_current_orb_basket_periods": beat_baseline_periods,
                "beat_current_orb_basket_share": beat_baseline_share,
                "total_test_trades": total_test_trades,
                "avg_test_trades_per_period": float(
                    group["test_selected_trades"].mean()
                ),
                "total_test_return": total_test_return,
                "avg_test_return": float(group["test_total_return"].mean()),
                "min_test_return": float(group["test_total_return"].min()),
                "max_test_return": float(group["test_total_return"].max()),
                "total_test_pnl_sek": total_test_pnl_sek,
                "avg_test_profit_factor": float(
                    pd.to_numeric(
                        group["test_profit_factor"],
                        errors="coerce",
                    ).replace(999.0, pd.NA).dropna().mean()
                    if not group["test_profit_factor"].empty
                    else 0.0
                ),
                "worst_test_drawdown": float(group["test_max_drawdown"].min()),
                "avg_train_return": float(group["train_total_return"].mean()),
                "avg_train_profit_factor": float(
                    pd.to_numeric(
                        group["train_profit_factor"],
                        errors="coerce",
                    ).replace(999.0, pd.NA).dropna().mean()
                    if not group["train_profit_factor"].empty
                    else 0.0
                ),
                "min_train_return": float(group["train_total_return"].min()),
                "max_train_return": float(group["train_total_return"].max()),
                "walkforward_candidate": walkforward_candidate,
            }
        )

    summary = pd.DataFrame(rows)

    if summary.empty:
        return summary

    summary = summary.sort_values(
        [
            "walkforward_candidate",
            "total_test_return",
            "positive_period_share",
            "avg_test_profit_factor",
        ],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    summary["walkforward_rank"] = summary.index + 1

    return summary


def main() -> None:
    print("\n=== STRATEGY LAB TICKER WALK-FORWARD ===")
    print("Research-only. This does not modify ORB paper/live trading.")
    print("Purpose: test whether optimized ticker baskets survive forward periods.")
    print(f"Train window days: {TRAIN_WINDOW_DAYS}")
    print(f"Test window days : {TEST_WINDOW_DAYS}")
    print(f"Step days        : {STEP_DAYS}")
    print(f"Initial capital  : {ORB_INITIAL_CAPITAL:.2f} SEK")
    print(f"Position size    : {ORB_POSITION_SIZE:.2%}")

    raw_prices = load_normalised_intraday_prices()
    all_tickers = discover_downloaded_tickers(raw_prices)

    print(f"\nDownloaded ticker count: {len(all_tickers)}")
    print(", ".join(all_tickers))

    market_regime = calculate_daily_market_regime(raw_prices)

    candidates = build_all_strategy_candidates(
        raw_prices=raw_prices,
        all_tickers=all_tickers,
        market_regime=market_regime,
    )

    if candidates.empty:
        print("No candidates created.")
        return

    candidates = normalise_dates(candidates)

    unique_dates = sorted(candidates["date"].dropna().unique())

    periods = build_walkforward_periods(unique_dates)

    if periods.empty:
        print("Not enough dates to build walk-forward periods.")
        return

    print("\n=== WALK-FORWARD PERIODS ===")
    display_period_cols = [
        "period_id",
        "train_start_date",
        "train_end_date",
        "test_start_date",
        "test_end_date",
        "train_days",
        "test_days",
    ]
    print(periods[display_period_cols].to_string(index=False))

    result_rows = []
    train_choice_frames = []
    test_trade_frames = []
    test_equity_frames = []

    for _, period in periods.iterrows():
        period_id = period["period_id"]

        train_dates = str(period["train_dates"]).split(",")
        test_dates = str(period["test_dates"]).split(",")

        train_candidates = filter_candidates_by_dates(candidates, train_dates)
        test_candidates = filter_candidates_by_dates(candidates, test_dates)

        print(f"\n=== {period_id} ===")
        print(
            f"Train: {period['train_start_date']} -> {period['train_end_date']} "
            f"({len(train_dates)} days, {len(train_candidates)} candidates)"
        )
        print(
            f"Test : {period['test_start_date']} -> {period['test_end_date']} "
            f"({len(test_dates)} days, {len(test_candidates)} candidates)"
        )

        print("Building train-period individual ticker performance...")
        train_ticker_performance = build_ticker_performance(
            candidates=train_candidates,
            all_tickers=all_tickers,
        )

        print("Optimizing train-period baskets...")
        train_basket_optimization = build_basket_optimization(
            candidates=train_candidates,
            all_tickers=all_tickers,
            ticker_performance=train_ticker_performance,
        )

        train_choices = build_optimization_summary(train_basket_optimization)

        if train_choices.empty:
            print(f"No train choices created for {period_id}.")
            continue

        train_choices = train_choices.copy()
        train_choices["period_id"] = period_id
        train_choices["train_start_date"] = period["train_start_date"]
        train_choices["train_end_date"] = period["train_end_date"]
        train_choices["test_start_date"] = period["test_start_date"]
        train_choices["test_end_date"] = period["test_end_date"]
        train_choice_frames.append(train_choices)

        for _, choice in train_choices.iterrows():
            strategy_name = choice["strategy_name"]
            summary_role = choice["summary_role"]
            trained_basket_type = choice["basket_type"]
            basket_tickers = parse_ticker_string(choice["basket_tickers"])

            train_selected, train_equity, train_summary = evaluate_strategy_basket(
                candidates=train_candidates,
                strategy_name=strategy_name,
                summary_role=summary_role,
                basket_tickers=basket_tickers,
            )

            test_selected, test_equity, test_summary = evaluate_strategy_basket(
                candidates=test_candidates,
                strategy_name=strategy_name,
                summary_role=summary_role,
                basket_tickers=basket_tickers,
            )

            result_row = {
                "period_id": period_id,
                "train_start_date": period["train_start_date"],
                "train_end_date": period["train_end_date"],
                "test_start_date": period["test_start_date"],
                "test_end_date": period["test_end_date"],
                "strategy_name": strategy_name,
                "summary_role": summary_role,
                "trained_basket_type": trained_basket_type,
                "basket_tickers": ", ".join(sorted(basket_tickers)),
                "basket_ticker_count": len(basket_tickers),
            }

            result_row.update(prefix_summary(train_summary, "train"))
            result_row.update(prefix_summary(test_summary, "test"))

            result_rows.append(result_row)

            test_selected = add_walkforward_metadata(
                df=test_selected,
                period=period,
                strategy_name=strategy_name,
                summary_role=summary_role,
                trained_basket_type=trained_basket_type,
                basket_tickers=basket_tickers,
                evaluation_phase="test",
            )

            if not test_selected.empty:
                test_trade_frames.append(test_selected)

            test_equity = add_walkforward_metadata(
                df=test_equity,
                period=period,
                strategy_name=strategy_name,
                summary_role=summary_role,
                trained_basket_type=trained_basket_type,
                basket_tickers=basket_tickers,
                evaluation_phase="test",
            )

            if not test_equity.empty:
                test_equity_frames.append(test_equity)

    results = pd.DataFrame(result_rows)

    if results.empty:
        print("No walk-forward results created.")
        return

    results = build_baseline_comparison_fields(results)
    summary = build_walkforward_summary(results)

    train_choices_all = (
        pd.concat(train_choice_frames, ignore_index=True)
        if train_choice_frames
        else pd.DataFrame()
    )

    test_trades = (
        pd.concat(test_trade_frames, ignore_index=True)
        if test_trade_frames
        else pd.DataFrame()
    )

    test_equity = (
        pd.concat(test_equity_frames, ignore_index=True)
        if test_equity_frames
        else pd.DataFrame()
    )

    export_csv_for_power_bi(periods, OUTPUT_PERIODS_FILE)
    export_csv_for_power_bi(results, OUTPUT_RESULTS_FILE)
    export_csv_for_power_bi(summary, OUTPUT_SUMMARY_FILE)
    export_csv_for_power_bi(test_trades, OUTPUT_TRADES_FILE)
    export_csv_for_power_bi(test_equity, OUTPUT_EQUITY_FILE)
    export_csv_for_power_bi(train_choices_all, OUTPUT_TRAIN_CHOICES_FILE)

    print("\n=== WALK-FORWARD SUMMARY ===")

    display_summary_cols = [
        "walkforward_rank",
        "strategy_name",
        "summary_role",
        "periods_tested",
        "positive_test_periods",
        "positive_period_share",
        "beat_current_orb_basket_periods",
        "total_test_trades",
        "total_test_return",
        "avg_test_return",
        "min_test_return",
        "avg_test_profit_factor",
        "worst_test_drawdown",
        "walkforward_candidate",
    ]

    print(summary[display_summary_cols].to_string(index=False))

    print("\n=== WALK-FORWARD RESULTS ===")

    display_result_cols = [
        "period_id",
        "strategy_name",
        "summary_role",
        "basket_ticker_count",
        "basket_tickers",
        "train_total_return",
        "test_total_return",
        "test_selected_trades",
        "test_profit_factor",
        "test_max_drawdown",
        "test_excess_return_vs_current_orb_basket",
    ]

    print(results[display_result_cols].to_string(index=False))

    print(f"\nSaved periods       -> {OUTPUT_PERIODS_FILE}")
    print(f"Saved results       -> {OUTPUT_RESULTS_FILE}")
    print(f"Saved summary       -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved test trades   -> {OUTPUT_TRADES_FILE}")
    print(f"Saved test equity   -> {OUTPUT_EQUITY_FILE}")
    print(f"Saved train choices -> {OUTPUT_TRAIN_CHOICES_FILE}")


if __name__ == "__main__":
    main()