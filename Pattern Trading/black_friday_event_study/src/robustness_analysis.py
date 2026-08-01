from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .database import read_table, write_table
from .settings import OUTPUT_DIR


SAMPLE_DEFINITIONS = {
    "Full_2010_2025": lambda df: pd.Series(
        True,
        index=df.index,
    ),
    "Discovery_2010_2018": lambda df: (
        df["event_year"] <= 2018
    ),
    "Validation_2019_2025": lambda df: (
        df["event_year"] >= 2019
    ),
}

BOOTSTRAP_ITERATIONS = 20_000
BOOTSTRAP_CONFIDENCE = 0.95
WINSOR_LIMIT = 0.10
BASE_RANDOM_SEED = 20260722


def _one_sided_t_test(
    values: np.ndarray,
) -> tuple[float, float]:
    """
    Tests:

        H0: mean <= 0
        H1: mean > 0
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) < 2:
        return np.nan, np.nan

    mean_value = float(np.mean(values))
    standard_deviation = float(
        np.std(values, ddof=1)
    )

    if np.isclose(standard_deviation, 0.0):
        if mean_value > 0:
            return np.inf, 0.0

        if mean_value < 0:
            return -np.inf, 1.0

        return np.nan, 1.0

    result = stats.ttest_1samp(
        values,
        popmean=0.0,
        nan_policy="omit",
    )

    t_stat = float(result.statistic)
    two_sided_p = float(result.pvalue)

    if t_stat > 0:
        one_sided_p = two_sided_p / 2
    else:
        one_sided_p = 1 - two_sided_p / 2

    return t_stat, float(one_sided_p)


def _sign_test(
    values: np.ndarray,
) -> tuple[int, int, float]:
    """
    Exact binomial sign test.

    Zero observations are excluded.
    Tests whether positive observations occur more often than 50%.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    nonzero = values[
        ~np.isclose(values, 0.0)
    ]

    n_nonzero = len(nonzero)
    positive_count = int(
        np.sum(nonzero > 0)
    )

    if n_nonzero == 0:
        return 0, 0, 1.0

    result = stats.binomtest(
        k=positive_count,
        n=n_nonzero,
        p=0.5,
        alternative="greater",
    )

    return (
        positive_count,
        n_nonzero,
        float(result.pvalue),
    )


def _wilcoxon_test(
    values: np.ndarray,
) -> tuple[float, float]:
    """
    One-sided Wilcoxon signed-rank test:

        H1: distribution is shifted above zero.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    nonzero = values[
        ~np.isclose(values, 0.0)
    ]

    if len(nonzero) < 2:
        return np.nan, np.nan

    try:
        result = stats.wilcoxon(
            nonzero,
            alternative="greater",
            zero_method="wilcox",
            method="auto",
        )

        return (
            float(result.statistic),
            float(result.pvalue),
        )

    except ValueError:
        return np.nan, np.nan


def _winsorized_mean(
    values: np.ndarray,
    limit: float = WINSOR_LIMIT,
) -> float:
    """
    Clips observations at the 10th and 90th percentiles.

    Returns NaN for samples smaller than five years because
    winsorization is not meaningful in extremely small samples.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) < 5:
        return np.nan

    lower = float(
        np.quantile(values, limit)
    )

    upper = float(
        np.quantile(values, 1 - limit)
    )

    clipped = np.clip(
        values,
        lower,
        upper,
    )

    return float(np.mean(clipped))


def _bootstrap_mean_ci(
    values: np.ndarray,
    seed: int,
    iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = BOOTSTRAP_CONFIDENCE,
) -> tuple[float, float]:
    """
    Non-parametric percentile bootstrap confidence interval
    for the arithmetic mean.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) == 0:
        return np.nan, np.nan

    if len(values) == 1:
        single_value = float(values[0])
        return single_value, single_value

    rng = np.random.default_rng(seed)

    resampled = rng.choice(
        values,
        size=(iterations, len(values)),
        replace=True,
    )

    bootstrap_means = resampled.mean(axis=1)

    alpha = 1 - confidence

    lower = float(
        np.quantile(
            bootstrap_means,
            alpha / 2,
        )
    )

    upper = float(
        np.quantile(
            bootstrap_means,
            1 - alpha / 2,
        )
    )

    return lower, upper


def _mean_excluding_index(
    values: np.ndarray,
    index_to_remove: int,
) -> float:
    values = np.asarray(values, dtype=float)

    if len(values) <= 1:
        return np.nan

    remaining = np.delete(
        values,
        index_to_remove,
    )

    return float(np.mean(remaining))


def _add_full_sample_fdr(
    summary: pd.DataFrame,
    p_value_column: str,
    output_column: str,
) -> None:
    summary[output_column] = np.nan

    mask = (
        summary["sample"].eq(
            "Full_2010_2025"
        )
        & summary[p_value_column].notna()
    )

    if not mask.any():
        return

    _, corrected, _, _ = multipletests(
        summary.loc[
            mask,
            p_value_column,
        ].astype(float),
        alpha=0.05,
        method="fdr_bh",
    )

    summary.loc[
        mask,
        output_column,
    ] = corrected


def run_robustness_analysis() -> dict[str, pd.DataFrame]:
    annual = read_table(
        "placebo_year_results"
    )

    annual["event_year"] = (
        annual["event_year"].astype(int)
    )

    annual = annual.sort_values(
        [
            "strategy",
            "event_year",
        ]
    ).reset_index(drop=True)

    required_columns = {
        "strategy",
        "ticker",
        "model_name",
        "event_year",
        "actual_car",
        "placebo_adjusted_car",
        "event_percentile",
        "top_decile_event",
    }

    missing_columns = (
        required_columns
        - set(annual.columns)
    )

    if missing_columns:
        raise RuntimeError(
            "placebo_year_results is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    summary_rows: list[dict] = []
    leave_one_out_rows: list[dict] = []

    strategy_order = {
        strategy: position
        for position, strategy in enumerate(
            annual["strategy"].drop_duplicates()
        )
    }

    analysis_counter = 0

    for strategy, strategy_data in annual.groupby(
        "strategy",
        sort=False,
    ):
        ticker = str(
            strategy_data["ticker"].iloc[0]
        )

        model_name = str(
            strategy_data["model_name"].iloc[0]
        )

        for sample_name, mask_function in (
            SAMPLE_DEFINITIONS.items()
        ):
            sample_mask = mask_function(
                strategy_data
            )

            sample = (
                strategy_data[
                    sample_mask
                ]
                .sort_values("event_year")
                .reset_index(drop=True)
            )

            if sample.empty:
                continue

            n_years = len(sample)

            actual = sample[
                "actual_car"
            ].to_numpy(dtype=float)

            excess = sample[
                "placebo_adjusted_car"
            ].to_numpy(dtype=float)

            years = sample[
                "event_year"
            ].to_numpy(dtype=int)

            actual_best_index = int(
                np.argmax(actual)
            )

            actual_worst_index = int(
                np.argmin(actual)
            )

            excess_best_index = int(
                np.argmax(excess)
            )

            excess_worst_index = int(
                np.argmin(excess)
            )

            actual_t_stat, actual_t_p = (
                _one_sided_t_test(actual)
            )

            excess_t_stat, excess_t_p = (
                _one_sided_t_test(excess)
            )

            (
                actual_sign_positive,
                actual_sign_n,
                actual_sign_p,
            ) = _sign_test(actual)

            (
                excess_sign_positive,
                excess_sign_n,
                excess_sign_p,
            ) = _sign_test(excess)

            (
                actual_wilcoxon_stat,
                actual_wilcoxon_p,
            ) = _wilcoxon_test(actual)

            (
                excess_wilcoxon_stat,
                excess_wilcoxon_p,
            ) = _wilcoxon_test(excess)

            analysis_counter += 1

            actual_bootstrap_low, actual_bootstrap_high = (
                _bootstrap_mean_ci(
                    actual,
                    seed=(
                        BASE_RANDOM_SEED
                        + analysis_counter * 10
                    ),
                )
            )

            excess_bootstrap_low, excess_bootstrap_high = (
                _bootstrap_mean_ci(
                    excess,
                    seed=(
                        BASE_RANDOM_SEED
                        + analysis_counter * 10
                        + 1
                    ),
                )
            )

            local_leave_one_out: list[dict] = []

            if n_years > 1:
                for omitted_index in range(
                    n_years
                ):
                    keep_mask = np.ones(
                        n_years,
                        dtype=bool,
                    )

                    keep_mask[
                        omitted_index
                    ] = False

                    remaining_actual = actual[
                        keep_mask
                    ]

                    remaining_excess = excess[
                        keep_mask
                    ]

                    loo_row = {
                        "strategy": strategy,
                        "ticker": ticker,
                        "model_name": model_name,
                        "sample": sample_name,
                        "omitted_year": int(
                            years[
                                omitted_index
                            ]
                        ),
                        "remaining_years": (
                            n_years - 1
                        ),
                        "actual_mean_car": float(
                            np.mean(
                                remaining_actual
                            )
                        ),
                        "actual_median_car": float(
                            np.median(
                                remaining_actual
                            )
                        ),
                        "actual_positive_rate": float(
                            np.mean(
                                remaining_actual > 0
                            )
                        ),
                        "excess_mean_car": float(
                            np.mean(
                                remaining_excess
                            )
                        ),
                        "excess_median_car": float(
                            np.median(
                                remaining_excess
                            )
                        ),
                        "excess_positive_rate": float(
                            np.mean(
                                remaining_excess > 0
                            )
                        ),
                    }

                    local_leave_one_out.append(
                        loo_row
                    )

                    leave_one_out_rows.append(
                        loo_row
                    )

            local_loo = pd.DataFrame(
                local_leave_one_out
            )

            if local_loo.empty:
                loo_min_actual_mean = np.nan
                loo_min_actual_year = np.nan
                loo_max_actual_mean = np.nan
                loo_max_actual_year = np.nan

                loo_min_excess_mean = np.nan
                loo_min_excess_year = np.nan
                loo_max_excess_mean = np.nan
                loo_max_excess_year = np.nan

            else:
                min_actual_row = (
                    local_loo.loc[
                        local_loo[
                            "actual_mean_car"
                        ].idxmin()
                    ]
                )

                max_actual_row = (
                    local_loo.loc[
                        local_loo[
                            "actual_mean_car"
                        ].idxmax()
                    ]
                )

                min_excess_row = (
                    local_loo.loc[
                        local_loo[
                            "excess_mean_car"
                        ].idxmin()
                    ]
                )

                max_excess_row = (
                    local_loo.loc[
                        local_loo[
                            "excess_mean_car"
                        ].idxmax()
                    ]
                )

                loo_min_actual_mean = float(
                    min_actual_row[
                        "actual_mean_car"
                    ]
                )

                loo_min_actual_year = int(
                    min_actual_row[
                        "omitted_year"
                    ]
                )

                loo_max_actual_mean = float(
                    max_actual_row[
                        "actual_mean_car"
                    ]
                )

                loo_max_actual_year = int(
                    max_actual_row[
                        "omitted_year"
                    ]
                )

                loo_min_excess_mean = float(
                    min_excess_row[
                        "excess_mean_car"
                    ]
                )

                loo_min_excess_year = int(
                    min_excess_row[
                        "omitted_year"
                    ]
                )

                loo_max_excess_mean = float(
                    max_excess_row[
                        "excess_mean_car"
                    ]
                )

                loo_max_excess_year = int(
                    max_excess_row[
                        "omitted_year"
                    ]
                )

            summary_rows.append(
                {
                    "strategy": strategy,
                    "strategy_order": (
                        strategy_order[strategy]
                    ),
                    "ticker": ticker,
                    "model_name": model_name,
                    "sample": sample_name,
                    "n_years": n_years,

                    "actual_mean_car": float(
                        np.mean(actual)
                    ),
                    "actual_median_car": float(
                        np.median(actual)
                    ),
                    "actual_std_car": (
                        float(
                            np.std(
                                actual,
                                ddof=1,
                            )
                        )
                        if n_years > 1
                        else np.nan
                    ),
                    "actual_positive_rate": float(
                        np.mean(actual > 0)
                    ),
                    "actual_worst_car": float(
                        np.min(actual)
                    ),
                    "actual_worst_year": int(
                        years[
                            actual_worst_index
                        ]
                    ),
                    "actual_best_car": float(
                        np.max(actual)
                    ),
                    "actual_best_year": int(
                        years[
                            actual_best_index
                        ]
                    ),
                    "actual_mean_excluding_best": (
                        _mean_excluding_index(
                            actual,
                            actual_best_index,
                        )
                    ),
                    "actual_mean_excluding_worst": (
                        _mean_excluding_index(
                            actual,
                            actual_worst_index,
                        )
                    ),
                    "actual_winsorized_mean": (
                        _winsorized_mean(actual)
                    ),
                    "actual_bootstrap_95_low": (
                        actual_bootstrap_low
                    ),
                    "actual_bootstrap_95_high": (
                        actual_bootstrap_high
                    ),
                    "actual_t_stat": (
                        actual_t_stat
                    ),
                    "actual_t_p_one_sided": (
                        actual_t_p
                    ),
                    "actual_sign_positive": (
                        actual_sign_positive
                    ),
                    "actual_sign_n": (
                        actual_sign_n
                    ),
                    "actual_sign_p_one_sided": (
                        actual_sign_p
                    ),
                    "actual_wilcoxon_stat": (
                        actual_wilcoxon_stat
                    ),
                    "actual_wilcoxon_p_one_sided": (
                        actual_wilcoxon_p
                    ),

                    "excess_mean_car": float(
                        np.mean(excess)
                    ),
                    "excess_median_car": float(
                        np.median(excess)
                    ),
                    "excess_std_car": (
                        float(
                            np.std(
                                excess,
                                ddof=1,
                            )
                        )
                        if n_years > 1
                        else np.nan
                    ),
                    "excess_positive_rate": float(
                        np.mean(excess > 0)
                    ),
                    "excess_worst_car": float(
                        np.min(excess)
                    ),
                    "excess_worst_year": int(
                        years[
                            excess_worst_index
                        ]
                    ),
                    "excess_best_car": float(
                        np.max(excess)
                    ),
                    "excess_best_year": int(
                        years[
                            excess_best_index
                        ]
                    ),
                    "excess_mean_excluding_best": (
                        _mean_excluding_index(
                            excess,
                            excess_best_index,
                        )
                    ),
                    "excess_mean_excluding_worst": (
                        _mean_excluding_index(
                            excess,
                            excess_worst_index,
                        )
                    ),
                    "excess_winsorized_mean": (
                        _winsorized_mean(excess)
                    ),
                    "excess_bootstrap_95_low": (
                        excess_bootstrap_low
                    ),
                    "excess_bootstrap_95_high": (
                        excess_bootstrap_high
                    ),
                    "excess_t_stat": (
                        excess_t_stat
                    ),
                    "excess_t_p_one_sided": (
                        excess_t_p
                    ),
                    "excess_sign_positive": (
                        excess_sign_positive
                    ),
                    "excess_sign_n": (
                        excess_sign_n
                    ),
                    "excess_sign_p_one_sided": (
                        excess_sign_p
                    ),
                    "excess_wilcoxon_stat": (
                        excess_wilcoxon_stat
                    ),
                    "excess_wilcoxon_p_one_sided": (
                        excess_wilcoxon_p
                    ),

                    "mean_event_percentile": float(
                        sample[
                            "event_percentile"
                        ].mean()
                    ),
                    "median_event_percentile": float(
                        sample[
                            "event_percentile"
                        ].median()
                    ),
                    "top_decile_year_rate": float(
                        sample[
                            "top_decile_event"
                        ].astype(bool).mean()
                    ),

                    "loo_min_actual_mean": (
                        loo_min_actual_mean
                    ),
                    "loo_min_actual_omitted_year": (
                        loo_min_actual_year
                    ),
                    "loo_max_actual_mean": (
                        loo_max_actual_mean
                    ),
                    "loo_max_actual_omitted_year": (
                        loo_max_actual_year
                    ),
                    "loo_min_excess_mean": (
                        loo_min_excess_mean
                    ),
                    "loo_min_excess_omitted_year": (
                        loo_min_excess_year
                    ),
                    "loo_max_excess_mean": (
                        loo_max_excess_mean
                    ),
                    "loo_max_excess_omitted_year": (
                        loo_max_excess_year
                    ),

                    "small_sample_warning": (
                        n_years < 8
                    ),
                }
            )

    summary = pd.DataFrame(
        summary_rows
    )

    leave_one_out = pd.DataFrame(
        leave_one_out_rows
    )

    _add_full_sample_fdr(
        summary,
        p_value_column=(
            "excess_t_p_one_sided"
        ),
        output_column=(
            "excess_t_p_one_sided_fdr"
        ),
    )

    _add_full_sample_fdr(
        summary,
        p_value_column=(
            "excess_sign_p_one_sided"
        ),
        output_column=(
            "excess_sign_p_one_sided_fdr"
        ),
    )

    _add_full_sample_fdr(
        summary,
        p_value_column=(
            "excess_wilcoxon_p_one_sided"
        ),
        output_column=(
            "excess_wilcoxon_p_one_sided_fdr"
        ),
    )

    summary = summary.sort_values(
        [
            "strategy_order",
            "sample",
        ]
    ).reset_index(drop=True)

    leave_one_out = leave_one_out.sort_values(
        [
            "strategy",
            "sample",
            "omitted_year",
        ]
    ).reset_index(drop=True)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = {
        "robustness_summary": summary,
        "robustness_leave_one_out": (
            leave_one_out
        ),
    }

    for name, dataframe in outputs.items():
        dataframe.to_csv(
            OUTPUT_DIR / f"{name}.csv",
            index=False,
        )

        write_table(
            dataframe,
            name,
        )

    print(
        "Robustness analysis completed."
    )

    print(
        f"Created {len(summary)} summary rows "
        f"and {len(leave_one_out)} "
        "leave-one-out rows."
    )

    return outputs


if __name__ == "__main__":
    run_robustness_analysis()