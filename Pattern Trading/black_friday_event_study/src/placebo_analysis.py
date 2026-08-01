from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .database import read_table, write_table
from .settings import OUTPUT_DIR


# These hypotheses are now frozen.
CANDIDATES = [
    {
        "strategy": "XRT_vs_SPY",
        "ticker": "XRT",
        "model_name": "SPY",
    },
    {
        "strategy": "WMT_vs_SPY_XRT",
        "ticker": "WMT",
        "model_name": "SPY_XRT",
    },
    {
        "strategy": "AMZN_vs_SPY_XRT",
        "ticker": "AMZN",
        "model_name": "SPY_XRT",
    },
    {
        "strategy": "ETSY_vs_SPY_XRT",
        "ticker": "ETSY",
        "model_name": "SPY_XRT",
    },
]

# Frozen real event window.
ACTUAL_START = -3
ACTUAL_END = 1
WINDOW_LENGTH = 5

# Nearby seasonal comparison period.
# All five-trading-day windows fully contained within -40 through +20
# will be evaluated.
PLACEBO_MIN_DAY = -40
PLACEBO_MAX_DAY = 20


def _window_car(
    year_panel: pd.DataFrame,
    start_day: int,
    end_day: int,
) -> float:
    sample = year_panel[
        year_panel["relative_day"].between(
            start_day,
            end_day,
        )
    ]

    expected_days = end_day - start_day + 1

    if (
        len(sample) != expected_days
        or sample["relative_day"].nunique() != expected_days
    ):
        return np.nan

    return float(sample["abnormal_return"].sum())


def _placebo_windows() -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []

    latest_start = (
        PLACEBO_MAX_DAY
        - WINDOW_LENGTH
        + 1
    )

    for start_day in range(
        PLACEBO_MIN_DAY,
        latest_start + 1,
    ):
        end_day = start_day + WINDOW_LENGTH - 1

        # Exclude all placebo windows that overlap the real event.
        overlaps_actual = (
            start_day <= ACTUAL_END
            and end_day >= ACTUAL_START
        )

        if overlaps_actual:
            continue

        windows.append((start_day, end_day))

    return windows


def _one_sided_t_test(
    values: pd.Series,
) -> tuple[float, float]:
    values = values.dropna().astype(float)

    if len(values) < 2:
        return np.nan, np.nan

    result = stats.ttest_1samp(
        values,
        popmean=0.0,
        nan_policy="omit",
    )

    t_stat = float(result.statistic)
    two_sided_p = float(result.pvalue)

    if np.isnan(t_stat) or np.isnan(two_sided_p):
        return t_stat, np.nan

    # Convert the two-sided test into:
    # H1: mean placebo-adjusted CAR > 0
    if t_stat > 0:
        one_sided_p = two_sided_p / 2
    else:
        one_sided_p = 1 - (two_sided_p / 2)

    return t_stat, one_sided_p


def _sample_mask(
    dataframe: pd.DataFrame,
    sample_name: str,
) -> pd.Series:
    if sample_name == "Full_2010_2025":
        return pd.Series(
            True,
            index=dataframe.index,
        )

    if sample_name == "Discovery_2010_2018":
        return dataframe["event_year"] <= 2018

    if sample_name == "Validation_2019_2025":
        return dataframe["event_year"] >= 2019

    raise ValueError(
        f"Unknown sample: {sample_name}"
    )


def run_placebo_analysis() -> dict[str, pd.DataFrame]:
    panel = read_table("event_panel")

    panel["event_year"] = (
        panel["event_year"].astype(int)
    )

    panel["relative_day"] = (
        panel["relative_day"].astype(int)
    )

    placebo_windows = _placebo_windows()

    annual_rows: list[dict] = []
    detail_rows: list[dict] = []

    for candidate in CANDIDATES:
        strategy = candidate["strategy"]
        ticker = candidate["ticker"]
        model_name = candidate["model_name"]

        candidate_panel = panel[
            (panel["ticker"] == ticker)
            & (panel["model_name"] == model_name)
        ].copy()

        if candidate_panel.empty:
            print(
                f"WARNING: no event-panel rows for "
                f"{ticker} / {model_name}"
            )
            continue

        for event_year, year_panel in candidate_panel.groupby(
            "event_year"
        ):
            year_panel = year_panel.sort_values(
                "relative_day"
            )

            actual_car = _window_car(
                year_panel,
                ACTUAL_START,
                ACTUAL_END,
            )

            if np.isnan(actual_car):
                continue

            current_placebos: list[float] = []

            for start_day, end_day in placebo_windows:
                placebo_car = _window_car(
                    year_panel,
                    start_day,
                    end_day,
                )

                if np.isnan(placebo_car):
                    continue

                current_placebos.append(placebo_car)

                detail_rows.append(
                    {
                        "strategy": strategy,
                        "ticker": ticker,
                        "model_name": model_name,
                        "event_year": int(event_year),
                        "placebo_start": start_day,
                        "placebo_end": end_day,
                        "placebo_car": placebo_car,
                    }
                )

            if not current_placebos:
                continue

            placebo_values = np.asarray(
                current_placebos,
                dtype=float,
            )

            median_placebo_car = float(
                np.median(placebo_values)
            )

            mean_placebo_car = float(
                np.mean(placebo_values)
            )

            # Percentage of nearby placebo windows beaten
            # by the real Thanksgiving window.
            event_percentile = float(
                np.mean(placebo_values < actual_car)
            )

            annual_empirical_p = float(
                (
                    1
                    + np.sum(
                        placebo_values >= actual_car
                    )
                )
                / (len(placebo_values) + 1)
            )

            annual_rows.append(
                {
                    "strategy": strategy,
                    "ticker": ticker,
                    "model_name": model_name,
                    "event_year": int(event_year),
                    "actual_car": actual_car,
                    "mean_placebo_car": mean_placebo_car,
                    "median_placebo_car": median_placebo_car,
                    "placebo_adjusted_car": (
                        actual_car
                        - median_placebo_car
                    ),
                    "event_percentile": event_percentile,
                    "top_decile_event": (
                        event_percentile >= 0.90
                    ),
                    "above_placebo_median": (
                        actual_car
                        > median_placebo_car
                    ),
                    "annual_empirical_p": (
                        annual_empirical_p
                    ),
                    "placebo_count": len(
                        placebo_values
                    ),
                }
            )

    annual = pd.DataFrame(annual_rows)
    details = pd.DataFrame(detail_rows)

    summary_rows: list[dict] = []
    start_summary_rows: list[dict] = []

    sample_names = [
        "Full_2010_2025",
        "Discovery_2010_2018",
        "Validation_2019_2025",
    ]

    for candidate in CANDIDATES:
        strategy = candidate["strategy"]
        ticker = candidate["ticker"]
        model_name = candidate["model_name"]

        strategy_annual = annual[
            annual["strategy"] == strategy
        ].copy()

        strategy_details = details[
            details["strategy"] == strategy
        ].copy()

        for sample_name in sample_names:
            annual_mask = _sample_mask(
                strategy_annual,
                sample_name,
            )

            annual_sample = strategy_annual[
                annual_mask
            ].copy()

            if annual_sample.empty:
                continue

            included_years = set(
                annual_sample["event_year"]
            )

            detail_sample = strategy_details[
                strategy_details[
                    "event_year"
                ].isin(included_years)
            ].copy()

            n_years = len(annual_sample)

            # Calculate the average return for each placebo
            # start date across the same set of years.
            placebo_start_summary = (
                detail_sample
                .groupby(
                    [
                        "placebo_start",
                        "placebo_end",
                    ],
                    as_index=False,
                )
                .agg(
                    mean_car=("placebo_car", "mean"),
                    median_car=("placebo_car", "median"),
                    year_count=(
                        "event_year",
                        "nunique",
                    ),
                )
            )

            # Use only placebo starts available in every year.
            placebo_start_summary = (
                placebo_start_summary[
                    placebo_start_summary[
                        "year_count"
                    ] == n_years
                ]
                .copy()
            )

            actual_mean = float(
                annual_sample["actual_car"].mean()
            )

            actual_median = float(
                annual_sample["actual_car"].median()
            )

            start_means = (
                placebo_start_summary["mean_car"]
                .to_numpy(dtype=float)
            )

            if len(start_means) > 0:
                # Sample-level empirical p-value:
                # how many nearby window positions have an
                # average return at least as large as the actual?
                empirical_window_p = float(
                    (
                        1
                        + np.sum(
                            start_means
                            >= actual_mean
                        )
                    )
                    / (len(start_means) + 1)
                )

                actual_window_percentile = float(
                    np.mean(
                        start_means < actual_mean
                    )
                )
            else:
                empirical_window_p = np.nan
                actual_window_percentile = np.nan

            t_stat, excess_p_value = (
                _one_sided_t_test(
                    annual_sample[
                        "placebo_adjusted_car"
                    ]
                )
            )

            summary_rows.append(
                {
                    "strategy": strategy,
                    "ticker": ticker,
                    "model_name": model_name,
                    "sample": sample_name,
                    "n_years": n_years,
                    "actual_mean_car": actual_mean,
                    "actual_median_car": actual_median,
                    "positive_actual_rate": float(
                        (
                            annual_sample[
                                "actual_car"
                            ] > 0
                        ).mean()
                    ),
                    "mean_yearly_median_placebo_car": float(
                        annual_sample[
                            "median_placebo_car"
                        ].mean()
                    ),
                    "mean_placebo_adjusted_car": float(
                        annual_sample[
                            "placebo_adjusted_car"
                        ].mean()
                    ),
                    "median_placebo_adjusted_car": float(
                        annual_sample[
                            "placebo_adjusted_car"
                        ].median()
                    ),
                    "positive_excess_rate": float(
                        (
                            annual_sample[
                                "placebo_adjusted_car"
                            ] > 0
                        ).mean()
                    ),
                    "mean_event_percentile": float(
                        annual_sample[
                            "event_percentile"
                        ].mean()
                    ),
                    "median_event_percentile": float(
                        annual_sample[
                            "event_percentile"
                        ].median()
                    ),
                    "top_decile_year_rate": float(
                        annual_sample[
                            "top_decile_event"
                        ].mean()
                    ),
                    "actual_window_percentile": (
                        actual_window_percentile
                    ),
                    "empirical_window_p_value": (
                        empirical_window_p
                    ),
                    "excess_t_stat": t_stat,
                    "excess_p_value_one_sided": (
                        excess_p_value
                    ),
                    "worst_actual_car": float(
                        annual_sample[
                            "actual_car"
                        ].min()
                    ),
                    "worst_placebo_adjusted_car": float(
                        annual_sample[
                            "placebo_adjusted_car"
                        ].min()
                    ),
                    "best_placebo_adjusted_car": float(
                        annual_sample[
                            "placebo_adjusted_car"
                        ].max()
                    ),
                    "placebo_start_count": len(
                        start_means
                    ),
                }
            )

            for row in placebo_start_summary.itertuples(
                index=False
            ):
                start_summary_rows.append(
                    {
                        "strategy": strategy,
                        "ticker": ticker,
                        "model_name": model_name,
                        "sample": sample_name,
                        "window_start": (
                            row.placebo_start
                        ),
                        "window_end": (
                            row.placebo_end
                        ),
                        "mean_car": row.mean_car,
                        "median_car": row.median_car,
                        "year_count": row.year_count,
                        "is_actual_window": False,
                    }
                )

            start_summary_rows.append(
                {
                    "strategy": strategy,
                    "ticker": ticker,
                    "model_name": model_name,
                    "sample": sample_name,
                    "window_start": ACTUAL_START,
                    "window_end": ACTUAL_END,
                    "mean_car": actual_mean,
                    "median_car": actual_median,
                    "year_count": n_years,
                    "is_actual_window": True,
                }
            )

    summary = pd.DataFrame(summary_rows)
    start_summary = pd.DataFrame(
        start_summary_rows
    )

    # Correct the four primary full-sample empirical tests.
    summary["empirical_window_p_fdr"] = np.nan
    summary["significant_fdr_10pct"] = False

    full_mask = (
        (summary["sample"] == "Full_2010_2025")
        & summary[
            "empirical_window_p_value"
        ].notna()
    )

    if full_mask.any():
        rejected, corrected, _, _ = multipletests(
            summary.loc[
                full_mask,
                "empirical_window_p_value",
            ],
            alpha=0.10,
            method="fdr_bh",
        )

        summary.loc[
            full_mask,
            "empirical_window_p_fdr",
        ] = corrected

        summary.loc[
            full_mask,
            "significant_fdr_10pct",
        ] = rejected

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = {
        "placebo_year_results": annual,
        "placebo_window_details": details,
        "placebo_summary": summary,
        "placebo_start_summary": start_summary,
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
        f"Created {len(annual)} annual strategy results."
    )

    print(
        f"Tested {len(_placebo_windows())} "
        "non-overlapping placebo windows per year."
    )

    return outputs


if __name__ == "__main__":
    run_placebo_analysis()