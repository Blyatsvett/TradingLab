from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .database import read_table, write_table
from .settings import OUTPUT_DIR


# Frozen before reviewing the portfolio results.
IMPLEMENTATIONS = {
    "AMZN": {
        "components": {"AMZN_vs_SPY_XRT": 1.00},
        "primary_sample": "Full_available_history",
    },
    "WMT": {
        "components": {"WMT_vs_SPY_XRT": 1.00},
        "primary_sample": "Validation_2019_2025",
    },
    "ETSY": {
        "components": {"ETSY_vs_SPY_XRT": 1.00},
        "primary_sample": "Validation_2019_2025",
    },
    "Portfolio_AMZN50_WMT50": {
        "components": {
            "AMZN_vs_SPY_XRT": 0.50,
            "WMT_vs_SPY_XRT": 0.50,
        },
        "primary_sample": "Full_available_history",
    },
    "Portfolio_AMZN40_WMT40_ETSY20": {
        "components": {
            "AMZN_vs_SPY_XRT": 0.40,
            "WMT_vs_SPY_XRT": 0.40,
            "ETSY_vs_SPY_XRT": 0.20,
        },
        "primary_sample": "Validation_2019_2025",
    },
}

TRADE_TYPES = ["LongOnly", "BetaHedged"]
COST_LEVELS_BPS = [25, 50]

SAMPLE_NAMES = [
    "Full_available_history",
    "Discovery_2010_2018",
    "Validation_2019_2025",
]

BOOTSTRAP_ITERATIONS = 30_000
BOOTSTRAP_CONFIDENCE = 0.95
BASE_RANDOM_SEED = 20260722
WINSOR_LIMIT = 0.10


def _sample_mask(dataframe: pd.DataFrame, sample: str) -> pd.Series:
    if sample == "Full_available_history":
        return pd.Series(True, index=dataframe.index)
    if sample == "Discovery_2010_2018":
        return dataframe["event_year"] <= 2018
    if sample == "Validation_2019_2025":
        return dataframe["event_year"] >= 2019
    raise ValueError(f"Unknown sample: {sample}")


def _max_drawdown(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan

    wealth = np.cumprod(1.0 + values)
    wealth_with_start = np.concatenate(([1.0], wealth))
    peaks = np.maximum.accumulate(wealth_with_start)
    return float(np.min(wealth_with_start / peaks - 1.0))


def _one_sided_t_test(values: np.ndarray) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return np.nan, np.nan

    standard_deviation = float(np.std(values, ddof=1))
    mean_value = float(np.mean(values))

    if np.isclose(standard_deviation, 0.0):
        if mean_value > 0:
            return np.inf, 0.0
        if mean_value < 0:
            return -np.inf, 1.0
        return np.nan, 1.0

    result = stats.ttest_1samp(values, popmean=0.0, nan_policy="omit")
    t_stat = float(result.statistic)
    two_sided_p = float(result.pvalue)
    one_sided_p = two_sided_p / 2 if t_stat > 0 else 1 - two_sided_p / 2
    return t_stat, float(one_sided_p)


def _sign_test(values: np.ndarray) -> tuple[int, int, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    nonzero = values[~np.isclose(values, 0.0)]

    if len(nonzero) == 0:
        return 0, 0, 1.0

    positive_count = int(np.sum(nonzero > 0))
    result = stats.binomtest(
        k=positive_count,
        n=len(nonzero),
        p=0.5,
        alternative="greater",
    )
    return positive_count, len(nonzero), float(result.pvalue)


def _wilcoxon_test(values: np.ndarray) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    nonzero = values[~np.isclose(values, 0.0)]

    if len(nonzero) < 2:
        return np.nan, np.nan

    try:
        result = stats.wilcoxon(
            nonzero,
            alternative="greater",
            zero_method="wilcox",
            method="auto",
        )
        return float(result.statistic), float(result.pvalue)
    except ValueError:
        return np.nan, np.nan


def _bootstrap_mean_ci(
    values: np.ndarray,
    seed: int,
    iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = BOOTSTRAP_CONFIDENCE,
) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) == 0:
        return np.nan, np.nan
    if len(values) == 1:
        return float(values[0]), float(values[0])

    rng = np.random.default_rng(seed)
    resampled = rng.choice(values, size=(iterations, len(values)), replace=True)
    bootstrap_means = resampled.mean(axis=1)
    alpha = 1.0 - confidence

    return (
        float(np.quantile(bootstrap_means, alpha / 2)),
        float(np.quantile(bootstrap_means, 1 - alpha / 2)),
    )


def _winsorized_mean(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 5:
        return np.nan

    lower = float(np.quantile(values, WINSOR_LIMIT))
    upper = float(np.quantile(values, 1 - WINSOR_LIMIT))
    return float(np.mean(np.clip(values, lower, upper)))


def _leave_one_out_rows(
    implementation: str,
    trade_type: str,
    cost_bps: int,
    sample: str,
    sample_data: pd.DataFrame,
) -> list[dict]:
    rows: list[dict] = []
    if len(sample_data) <= 1:
        return rows

    ordered = sample_data.sort_values("event_year").reset_index(drop=True)

    for omitted_index in range(len(ordered)):
        remaining = ordered.drop(index=omitted_index)
        values = remaining["net_return"].to_numpy(dtype=float)

        rows.append(
            {
                "implementation": implementation,
                "trade_type": trade_type,
                "cost_bps": cost_bps,
                "sample": sample,
                "omitted_year": int(ordered.loc[omitted_index, "event_year"]),
                "remaining_trades": len(remaining),
                "mean_return": float(np.mean(values)),
                "median_return": float(np.median(values)),
                "positive_rate": float(np.mean(values > 0)),
                "worst_return": float(np.min(values)),
                "max_drawdown": _max_drawdown(values),
            }
        )

    return rows


def _build_implementation_trades(source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    annual_rows: list[dict] = []
    diagnostic_rows: list[dict] = []

    required_source_columns = {
        "strategy",
        "event_year",
        "trade_type",
        "cost_bps",
        "gross_return",
        "transaction_cost",
        "net_return",
        "gross_notional",
        "entry_date",
        "exit_date",
    }
    missing = required_source_columns - set(source.columns)
    if missing:
        raise RuntimeError(
            "backtest_trade_results is missing columns: "
            + ", ".join(sorted(missing))
        )

    source = source.copy()
    source["event_year"] = source["event_year"].astype(int)
    source["cost_bps"] = source["cost_bps"].astype(int)
    source["entry_date"] = pd.to_datetime(source["entry_date"])
    source["exit_date"] = pd.to_datetime(source["exit_date"])

    duplicate_counts = (
        source.groupby(
            ["strategy", "event_year", "trade_type", "cost_bps"]
        )
        .size()
        .reset_index(name="row_count")
    )
    duplicates = duplicate_counts[duplicate_counts["row_count"] > 1]
    if not duplicates.empty:
        raise RuntimeError(
            "Duplicate annual strategy rows found in backtest_trade_results."
        )

    for implementation, definition in IMPLEMENTATIONS.items():
        components: dict[str, float] = definition["components"]
        weight_sum = float(sum(components.values()))
        if not np.isclose(weight_sum, 1.0):
            raise ValueError(
                f"Weights for {implementation} sum to {weight_sum}, not 1.0."
            )

        component_names = list(components)
        is_portfolio = len(component_names) > 1

        for trade_type in TRADE_TYPES:
            for cost_bps in COST_LEVELS_BPS:
                filtered = source[
                    source["strategy"].isin(component_names)
                    & source["trade_type"].eq(trade_type)
                    & source["cost_bps"].eq(cost_bps)
                ].copy()

                if filtered.empty:
                    diagnostic_rows.append(
                        {
                            "implementation": implementation,
                            "trade_type": trade_type,
                            "cost_bps": cost_bps,
                            "event_year": np.nan,
                            "status": "no_source_rows",
                            "detail": "",
                        }
                    )
                    continue

                year_sets = {
                    component: set(
                        filtered.loc[
                            filtered["strategy"].eq(component), "event_year"
                        ].astype(int)
                    )
                    for component in component_names
                }
                common_years = sorted(set.intersection(*year_sets.values()))
                all_years = sorted(set.union(*year_sets.values()))

                for missing_year in sorted(set(all_years) - set(common_years)):
                    missing_components = [
                        component
                        for component in component_names
                        if missing_year not in year_sets[component]
                    ]
                    diagnostic_rows.append(
                        {
                            "implementation": implementation,
                            "trade_type": trade_type,
                            "cost_bps": cost_bps,
                            "event_year": missing_year,
                            "status": "expected_history_gap",
                            "detail": ",".join(missing_components),
                        }
                    )

                for event_year in common_years:
                    year_rows = filtered[filtered["event_year"].eq(event_year)].copy()
                    year_rows = year_rows.set_index("strategy")

                    entry_dates = year_rows.loc[component_names, "entry_date"].unique()
                    exit_dates = year_rows.loc[component_names, "exit_date"].unique()
                    if len(entry_dates) != 1 or len(exit_dates) != 1:
                        diagnostic_rows.append(
                            {
                                "implementation": implementation,
                                "trade_type": trade_type,
                                "cost_bps": cost_bps,
                                "event_year": event_year,
                                "status": "date_mismatch",
                                "detail": "Component entry or exit dates differ.",
                            }
                        )
                        continue

                    weighted = lambda column: float(
                        sum(
                            components[component]
                            * float(year_rows.loc[component, column])
                            for component in component_names
                        )
                    )

                    annual_rows.append(
                        {
                            "implementation": implementation,
                            "primary_sample": definition["primary_sample"],
                            "is_portfolio": is_portfolio,
                            "component_weights": ";".join(
                                f"{component}:{components[component]:.2f}"
                                for component in component_names
                            ),
                            "component_count": len(component_names),
                            "trade_type": trade_type,
                            "cost_bps": cost_bps,
                            "event_year": event_year,
                            "entry_date": pd.Timestamp(entry_dates[0]),
                            "exit_date": pd.Timestamp(exit_dates[0]),
                            "gross_return": weighted("gross_return"),
                            "transaction_cost": weighted("transaction_cost"),
                            "net_return": weighted("net_return"),
                            "gross_notional": weighted("gross_notional"),
                        }
                    )

                    diagnostic_rows.append(
                        {
                            "implementation": implementation,
                            "trade_type": trade_type,
                            "cost_bps": cost_bps,
                            "event_year": event_year,
                            "status": "ok",
                            "detail": "",
                        }
                    )

    return pd.DataFrame(annual_rows), pd.DataFrame(diagnostic_rows)


def _summarize_implementation_returns(
    implementation_trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict] = []
    leave_one_out_rows: list[dict] = []
    analysis_counter = 0

    group_columns = ["implementation", "trade_type", "cost_bps"]

    for keys, group in implementation_trades.groupby(group_columns, sort=False):
        implementation, trade_type, cost_bps = keys
        primary_sample = str(group["primary_sample"].iloc[0])
        is_portfolio = bool(group["is_portfolio"].iloc[0])
        component_weights = str(group["component_weights"].iloc[0])

        for sample in SAMPLE_NAMES:
            sample_data = (
                group.loc[_sample_mask(group, sample)]
                .sort_values("event_year")
                .reset_index(drop=True)
            )
            if sample_data.empty:
                continue

            values = sample_data["net_return"].to_numpy(dtype=float)
            years = sample_data["event_year"].to_numpy(dtype=int)
            n = len(values)
            best_index = int(np.argmax(values))
            worst_index = int(np.argmin(values))

            analysis_counter += 1
            bootstrap_low, bootstrap_high = _bootstrap_mean_ci(
                values,
                seed=BASE_RANDOM_SEED + analysis_counter,
            )
            t_stat, t_p = _one_sided_t_test(values)
            sign_positive, sign_n, sign_p = _sign_test(values)
            wilcoxon_stat, wilcoxon_p = _wilcoxon_test(values)

            loo_rows = _leave_one_out_rows(
                implementation=implementation,
                trade_type=trade_type,
                cost_bps=int(cost_bps),
                sample=sample,
                sample_data=sample_data,
            )
            leave_one_out_rows.extend(loo_rows)

            if loo_rows:
                loo_frame = pd.DataFrame(loo_rows)
                min_loo_row = loo_frame.loc[loo_frame["mean_return"].idxmin()]
                max_loo_row = loo_frame.loc[loo_frame["mean_return"].idxmax()]
                loo_min_mean = float(min_loo_row["mean_return"])
                loo_min_omitted_year = int(min_loo_row["omitted_year"])
                loo_max_mean = float(max_loo_row["mean_return"])
                loo_max_omitted_year = int(max_loo_row["omitted_year"])
            else:
                loo_min_mean = np.nan
                loo_min_omitted_year = np.nan
                loo_max_mean = np.nan
                loo_max_omitted_year = np.nan

            without_2021 = sample_data[~sample_data["event_year"].eq(2021)]
            without_2021_values = without_2021["net_return"].to_numpy(dtype=float)

            growth = float(np.prod(1.0 + values))

            summary_rows.append(
                {
                    "implementation": implementation,
                    "primary_sample": primary_sample,
                    "is_primary_sample": sample == primary_sample,
                    "is_portfolio": is_portfolio,
                    "component_weights": component_weights,
                    "trade_type": trade_type,
                    "cost_bps": int(cost_bps),
                    "sample": sample,
                    "n_trades": n,
                    "first_year": int(np.min(years)),
                    "last_year": int(np.max(years)),
                    "mean_return": float(np.mean(values)),
                    "median_return": float(np.median(values)),
                    "std_return": float(np.std(values, ddof=1)) if n > 1 else np.nan,
                    "winsorized_mean": _winsorized_mean(values),
                    "positive_rate": float(np.mean(values > 0)),
                    "worst_return": float(values[worst_index]),
                    "worst_year": int(years[worst_index]),
                    "best_return": float(values[best_index]),
                    "best_year": int(years[best_index]),
                    "mean_excluding_best": (
                        float(np.mean(np.delete(values, best_index)))
                        if n > 1
                        else np.nan
                    ),
                    "mean_excluding_worst": (
                        float(np.mean(np.delete(values, worst_index)))
                        if n > 1
                        else np.nan
                    ),
                    "n_excluding_2021": len(without_2021_values),
                    "mean_excluding_2021": (
                        float(np.mean(without_2021_values))
                        if len(without_2021_values) > 0
                        else np.nan
                    ),
                    "median_excluding_2021": (
                        float(np.median(without_2021_values))
                        if len(without_2021_values) > 0
                        else np.nan
                    ),
                    "positive_rate_excluding_2021": (
                        float(np.mean(without_2021_values > 0))
                        if len(without_2021_values) > 0
                        else np.nan
                    ),
                    "bootstrap_95_low": bootstrap_low,
                    "bootstrap_95_high": bootstrap_high,
                    "t_stat": t_stat,
                    "t_p_one_sided": t_p,
                    "sign_positive": sign_positive,
                    "sign_n": sign_n,
                    "sign_p_one_sided": sign_p,
                    "wilcoxon_stat": wilcoxon_stat,
                    "wilcoxon_p_one_sided": wilcoxon_p,
                    "loo_min_mean": loo_min_mean,
                    "loo_min_omitted_year": loo_min_omitted_year,
                    "loo_max_mean": loo_max_mean,
                    "loo_max_omitted_year": loo_max_omitted_year,
                    "cumulative_return": growth - 1.0,
                    "geometric_mean_per_trade": (
                        float(growth ** (1.0 / n) - 1.0)
                        if growth > 0
                        else np.nan
                    ),
                    "max_drawdown": _max_drawdown(values),
                    "average_gross_notional": float(
                        sample_data["gross_notional"].mean()
                    ),
                    "small_sample_warning": n < 8,
                }
            )

    return pd.DataFrame(summary_rows), pd.DataFrame(leave_one_out_rows)


def _paired_hedge_comparison(
    implementation_trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paired_rows: list[dict] = []
    summary_rows: list[dict] = []
    analysis_counter = 0

    for (implementation, cost_bps), group in implementation_trades.groupby(
        ["implementation", "cost_bps"], sort=False
    ):
        pivot = group.pivot_table(
            index="event_year",
            columns="trade_type",
            values="net_return",
            aggfunc="first",
        ).dropna(subset=["LongOnly", "BetaHedged"])

        if pivot.empty:
            continue

        pivot = pivot.reset_index()
        pivot["implementation"] = implementation
        pivot["cost_bps"] = int(cost_bps)
        pivot["long_minus_hedged"] = pivot["LongOnly"] - pivot["BetaHedged"]

        for row in pivot.itertuples(index=False):
            paired_rows.append(
                {
                    "implementation": implementation,
                    "cost_bps": int(cost_bps),
                    "event_year": int(row.event_year),
                    "long_only_return": float(row.LongOnly),
                    "beta_hedged_return": float(row.BetaHedged),
                    "long_minus_hedged": float(row.long_minus_hedged),
                    "long_beats_hedge": bool(row.long_minus_hedged > 0),
                }
            )

        for sample in SAMPLE_NAMES:
            sample_data = pivot.loc[_sample_mask(pivot, sample)].copy()
            if sample_data.empty:
                continue

            differences = sample_data["long_minus_hedged"].to_numpy(dtype=float)
            analysis_counter += 1
            bootstrap_low, bootstrap_high = _bootstrap_mean_ci(
                differences,
                seed=BASE_RANDOM_SEED + 100_000 + analysis_counter,
            )
            t_stat, t_p = _one_sided_t_test(differences)
            sign_positive, sign_n, sign_p = _sign_test(differences)
            wilcoxon_stat, wilcoxon_p = _wilcoxon_test(differences)

            summary_rows.append(
                {
                    "implementation": implementation,
                    "cost_bps": int(cost_bps),
                    "sample": sample,
                    "n_pairs": len(sample_data),
                    "long_mean": float(sample_data["LongOnly"].mean()),
                    "hedged_mean": float(sample_data["BetaHedged"].mean()),
                    "mean_long_minus_hedged": float(np.mean(differences)),
                    "median_long_minus_hedged": float(np.median(differences)),
                    "long_beats_hedge_rate": float(np.mean(differences > 0)),
                    "difference_bootstrap_95_low": bootstrap_low,
                    "difference_bootstrap_95_high": bootstrap_high,
                    "difference_t_stat": t_stat,
                    "difference_t_p_one_sided": t_p,
                    "difference_sign_positive": sign_positive,
                    "difference_sign_n": sign_n,
                    "difference_sign_p_one_sided": sign_p,
                    "difference_wilcoxon_stat": wilcoxon_stat,
                    "difference_wilcoxon_p_one_sided": wilcoxon_p,
                    "small_sample_warning": len(sample_data) < 8,
                }
            )

    return pd.DataFrame(paired_rows), pd.DataFrame(summary_rows)


def _apply_fdr_by_family(
    dataframe: pd.DataFrame,
    p_column: str,
    output_column: str,
    group_columns: list[str],
    row_mask: pd.Series | None = None,
) -> None:
    dataframe[output_column] = np.nan

    base_mask = dataframe[p_column].notna()
    if row_mask is not None:
        base_mask &= row_mask

    eligible = dataframe.loc[base_mask]
    if eligible.empty:
        return

    for _, group in eligible.groupby(group_columns, dropna=False):
        _, corrected, _, _ = multipletests(
            group[p_column].astype(float),
            alpha=0.05,
            method="fdr_bh",
        )
        dataframe.loc[group.index, output_column] = corrected


def run_executable_validation() -> dict[str, pd.DataFrame]:
    source = read_table("backtest_trade_results")

    implementation_trades, diagnostics = _build_implementation_trades(source)
    if implementation_trades.empty:
        raise RuntimeError("No implementation trades were created.")

    summary, leave_one_out = _summarize_implementation_returns(
        implementation_trades
    )
    hedge_pairs, hedge_summary = _paired_hedge_comparison(
        implementation_trades
    )

    primary_long_mask = summary["trade_type"].eq("LongOnly")
    for p_column, output_column in [
        ("t_p_one_sided", "t_p_one_sided_fdr"),
        ("sign_p_one_sided", "sign_p_one_sided_fdr"),
        ("wilcoxon_p_one_sided", "wilcoxon_p_one_sided_fdr"),
    ]:
        _apply_fdr_by_family(
            summary,
            p_column=p_column,
            output_column=output_column,
            group_columns=["cost_bps", "sample"],
            row_mask=primary_long_mask,
        )

    for p_column, output_column in [
        ("difference_t_p_one_sided", "difference_t_p_one_sided_fdr"),
        ("difference_sign_p_one_sided", "difference_sign_p_one_sided_fdr"),
        (
            "difference_wilcoxon_p_one_sided",
            "difference_wilcoxon_p_one_sided_fdr",
        ),
    ]:
        _apply_fdr_by_family(
            hedge_summary,
            p_column=p_column,
            output_column=output_column,
            group_columns=["cost_bps", "sample"],
        )

    implementation_trades = implementation_trades.sort_values(
        ["implementation", "trade_type", "cost_bps", "event_year"]
    ).reset_index(drop=True)
    summary = summary.sort_values(
        ["implementation", "trade_type", "cost_bps", "sample"]
    ).reset_index(drop=True)
    leave_one_out = leave_one_out.sort_values(
        [
            "implementation",
            "trade_type",
            "cost_bps",
            "sample",
            "omitted_year",
        ]
    ).reset_index(drop=True)
    hedge_pairs = hedge_pairs.sort_values(
        ["implementation", "cost_bps", "event_year"]
    ).reset_index(drop=True)
    hedge_summary = hedge_summary.sort_values(
        ["implementation", "cost_bps", "sample"]
    ).reset_index(drop=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "execution_validation_trades": implementation_trades,
        "execution_validation_summary": summary,
        "execution_validation_leave_one_out": leave_one_out,
        "execution_hedge_pairs": hedge_pairs,
        "execution_hedge_summary": hedge_summary,
        "execution_validation_diagnostics": diagnostics,
    }

    for name, dataframe in outputs.items():
        dataframe.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        write_table(dataframe, name)

    ok_count = int((diagnostics["status"] == "ok").sum())
    error_count = int((~diagnostics["status"].isin(["ok", "expected_history_gap"])).sum())

    print("Executable-return validation completed.")
    print(
        f"Created {len(implementation_trades)} annual implementation rows, "
        f"{len(summary)} summary rows, and {len(hedge_summary)} hedge-comparison rows."
    )
    print(f"Diagnostics: {ok_count} ok rows and {error_count} error rows.")

    return outputs


if __name__ == "__main__":
    run_executable_validation()
