from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .database import read_table, write_table
from .settings import MIN_EVENT_YEARS, OUTPUT_DIR


def _summarize(values: pd.Series) -> pd.Series:
    values = values.dropna().astype(float)
    n = len(values)

    if n == 0:
        return pd.Series(dtype=float)

    mean = values.mean()

    std = (
        values.std(ddof=1)
        if n > 1
        else np.nan
    )

    t_result = (
        stats.ttest_1samp(
            values,
            popmean=0.0,
            nan_policy="omit",
        )
        if n > 1
        else None
    )

    return pd.Series(
        {
            "n_years": n,
            "mean_car": mean,
            "median_car": values.median(),
            "std_car": std,
            "positive_year_rate": (values > 0).mean(),
            "worst_year_car": values.min(),
            "best_year_car": values.max(),
            "t_stat": (
                t_result.statistic
                if t_result is not None
                else np.nan
            ),
            "p_value": (
                t_result.pvalue
                if t_result is not None
                else np.nan
            ),
        }
    )


def _build_summary(
    dataframe: pd.DataFrame,
    group_columns: list[str],
    value_column: str,
) -> pd.DataFrame:
    return (
        dataframe
        .groupby(group_columns)[value_column]
        .apply(_summarize)
        .unstack()
        .reset_index()
    )


def _add_fdr_columns(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    result = dataframe.copy()

    result["p_value_fdr"] = np.nan
    result["significant_fdr_5pct"] = False

    valid = result["p_value"].notna()

    if valid.any():
        rejected, corrected, _, _ = multipletests(
            result.loc[valid, "p_value"],
            alpha=0.05,
            method="fdr_bh",
        )

        result.loc[valid, "p_value_fdr"] = corrected
        result.loc[
            valid,
            "significant_fdr_5pct",
        ] = rejected

    return result


def run_analysis() -> dict[str, pd.DataFrame]:
    windows = read_table("event_windows")

    # One observation per model, group, year and event window.
    group_year = (
        windows
        .groupby(
            [
                "model_name",
                "exposure_group",
                "event_year",
                "window",
            ],
            as_index=False,
        )
        .agg(
            mean_group_car=("car", "mean"),
            median_group_car=("car", "median"),
            company_count=("ticker", "nunique"),
        )
    )

    group_summary = _build_summary(
        dataframe=group_year,
        group_columns=[
            "model_name",
            "exposure_group",
            "window",
        ],
        value_column="mean_group_car",
    )

    group_summary = _add_fdr_columns(
        group_summary
    )

    company_summary = _build_summary(
        dataframe=windows,
        group_columns=[
            "model_name",
            "ticker",
            "company_name",
            "exposure_group",
            "window",
        ],
        value_column="car",
    )

    company_summary = company_summary[
        company_summary["n_years"]
        >= MIN_EVENT_YEARS
    ].copy()

    panel = read_table("event_panel")

    group_curve = (
        panel
        .groupby(
            [
                "model_name",
                "exposure_group",
                "relative_day",
            ],
            as_index=False,
        )
        .agg(
            mean_abnormal_return=(
                "abnormal_return",
                "mean",
            ),
            mean_cumulative_abnormal_return=(
                "cumulative_abnormal_return",
                "mean",
            ),
            observations=(
                "abnormal_return",
                "size",
            ),
        )
    )

    split_data = group_year.assign(
        sample=np.where(
            group_year["event_year"] <= 2018,
            "Discovery_2010_2018",
            "Validation_2019_2025",
        )
    )

    split_results = _build_summary(
        dataframe=split_data,
        group_columns=[
            "sample",
            "model_name",
            "exposure_group",
            "window",
        ],
        value_column="mean_group_car",
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = {
        "group_year_cars": group_year,
        "group_summary": group_summary,
        "company_summary": company_summary,
        "group_curve": group_curve,
        "split_results": split_results,
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

    return outputs