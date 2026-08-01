from __future__ import annotations

import numpy as np
import pandas as pd

from .database import read_table, write_table
from .event_calendar import build_event_calendar
from .settings import (
    BENCHMARK_TICKERS,
    COMPANIES_CSV,
    ESTIMATION_END,
    ESTIMATION_START,
    EVENT_END_YEAR,
    EVENT_START_YEAR,
    EVENT_WINDOWS,
    FACTOR_MODELS,
    MIN_ESTIMATION_OBSERVATIONS,
    PANEL_END,
    PANEL_START,
    PROCESSED_DIR,
)


def _fit_factor_model(
    estimation: pd.DataFrame,
    factor_columns: list[str],
) -> tuple[float, dict[str, float]]:
    """
    Estimate:

        stock_return = alpha + beta_1 * factor_1 + ... + error
    """

    x = estimation[factor_columns].to_numpy(dtype=float)
    y = estimation["stock_return"].to_numpy(dtype=float)

    design = np.column_stack(
        [
            np.ones(len(x)),
            x,
        ]
    )

    coefficients = np.linalg.lstsq(
        design,
        y,
        rcond=None,
    )[0]

    alpha = float(coefficients[0])

    betas = {
        factor: float(beta)
        for factor, beta in zip(
            factor_columns,
            coefficients[1:],
        )
    }

    return alpha, betas


def build_event_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = read_table("daily_prices")
    prices["date"] = pd.to_datetime(prices["date"])

    companies = pd.read_csv(COMPANIES_CSV)

    events = build_event_calendar(
        EVENT_START_YEAR,
        EVENT_END_YEAR,
    )

    benchmark_prices = prices[
        prices["ticker"].isin(BENCHMARK_TICKERS)
    ].copy()

    benchmark_returns = (
        benchmark_prices
        .pivot(
            index="date",
            columns="ticker",
            values="daily_return",
        )
        .rename(
            columns=lambda ticker: f"{ticker}_return"
        )
        .reset_index()
    )

    required_benchmark_columns = [
        f"{ticker}_return"
        for ticker in BENCHMARK_TICKERS
    ]

    missing_benchmarks = [
        column
        for column in required_benchmark_columns
        if column not in benchmark_returns.columns
    ]

    if missing_benchmarks:
        raise RuntimeError(
            "Missing benchmark data: "
            + ", ".join(missing_benchmarks)
        )

    panel_rows: list[pd.DataFrame] = []
    diagnostic_rows: list[dict] = []

    for ticker in companies["ticker"]:
        stock = (
            prices.loc[
                prices["ticker"] == ticker,
                ["date", "daily_return"],
            ]
            .rename(
                columns={
                    "daily_return": "stock_return",
                }
            )
            .dropna()
        )

        merged = (
            stock
            .merge(
                benchmark_returns,
                on="date",
                how="inner",
            )
            .sort_values("date")
            .reset_index(drop=True)
        )

        if merged.empty:
            diagnostic_rows.append(
                {
                    "ticker": ticker,
                    "event_year": None,
                    "model_name": None,
                    "status": "no_merged_returns",
                }
            )
            continue

        for event in events.itertuples(index=False):
            matches = merged.index[
                merged["date"] == event.event_date
            ].tolist()

            if not matches:
                diagnostic_rows.append(
                    {
                        "ticker": ticker,
                        "event_year": event.event_year,
                        "model_name": None,
                        "status": "event_date_missing",
                    }
                )
                continue

            event_index = matches[0]

            local = merged.copy()

            local["relative_day"] = (
                np.arange(len(local)) - event_index
            )

            for model_name, factor_columns in FACTOR_MODELS.items():
                required_columns = [
                    "stock_return",
                    *factor_columns,
                ]

                estimation = local[
                    local["relative_day"].between(
                        ESTIMATION_START,
                        ESTIMATION_END,
                    )
                ].dropna(
                    subset=required_columns
                )

                if len(estimation) < MIN_ESTIMATION_OBSERVATIONS:
                    diagnostic_rows.append(
                        {
                            "ticker": ticker,
                            "event_year": event.event_year,
                            "model_name": model_name,
                            "status": "insufficient_estimation_data",
                        }
                    )
                    continue

                alpha, betas = _fit_factor_model(
                    estimation=estimation,
                    factor_columns=factor_columns,
                )

                event_panel = local[
                    local["relative_day"].between(
                        PANEL_START,
                        PANEL_END,
                    )
                ].dropna(
                    subset=required_columns
                ).copy()

                expected_return = pd.Series(
                    alpha,
                    index=event_panel.index,
                    dtype=float,
                )

                for factor_column in factor_columns:
                    expected_return = (
                        expected_return
                        + betas[factor_column]
                        * event_panel[factor_column]
                    )

                event_panel["expected_return"] = expected_return

                event_panel["abnormal_return"] = (
                    event_panel["stock_return"]
                    - event_panel["expected_return"]
                )

                event_panel["cumulative_abnormal_return"] = (
                    event_panel["abnormal_return"].cumsum()
                )

                event_panel["ticker"] = ticker
                event_panel["event_name"] = event.event_name
                event_panel["event_year"] = event.event_year
                event_panel["event_date"] = event.event_date
                event_panel["model_name"] = model_name
                event_panel["alpha"] = alpha

                event_panel["beta_spy"] = betas.get(
                    "SPY_return",
                    np.nan,
                )

                event_panel["beta_xrt"] = betas.get(
                    "XRT_return",
                    np.nan,
                )

                panel_rows.append(event_panel)

                diagnostic_rows.append(
                    {
                        "ticker": ticker,
                        "event_year": event.event_year,
                        "model_name": model_name,
                        "status": "ok",
                    }
                )

    if not panel_rows:
        raise RuntimeError(
            "No valid ticker-year event panels were created."
        )

    panel = pd.concat(
        panel_rows,
        ignore_index=True,
    )

    panel = panel.merge(
        companies,
        on="ticker",
        how="left",
    )

    key_columns = [
        "ticker",
        "company_name",
        "exposure_group",
        "model_name",
        "event_name",
        "event_year",
        "event_date",
    ]

    window_rows: list[dict] = []

    for keys, group in panel.groupby(
        key_columns,
        dropna=False,
    ):
        key_data = dict(
            zip(key_columns, keys)
        )

        for window_name, (
            start_day,
            end_day,
        ) in EVENT_WINDOWS.items():
            sample = group[
                group["relative_day"].between(
                    start_day,
                    end_day,
                )
            ]

            if sample.empty:
                continue

            window_rows.append(
                {
                    **key_data,
                    "window": window_name,
                    "window_start": start_day,
                    "window_end": end_day,
                    "car": sample["abnormal_return"].sum(),
                    "observations": len(sample),
                }
            )

    windows = pd.DataFrame(window_rows)
    diagnostics = pd.DataFrame(diagnostic_rows)

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    events.to_csv(
        PROCESSED_DIR / "events.csv",
        index=False,
    )

    panel.to_csv(
        PROCESSED_DIR / "event_panel.csv",
        index=False,
    )

    windows.to_csv(
        PROCESSED_DIR / "event_windows.csv",
        index=False,
    )

    diagnostics.to_csv(
        PROCESSED_DIR / "diagnostics.csv",
        index=False,
    )

    write_table(events, "events")
    write_table(companies, "companies")
    write_table(panel, "event_panel")
    write_table(windows, "event_windows")
    write_table(diagnostics, "diagnostics")

    return panel, windows