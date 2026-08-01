from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .database import read_table, write_table
from .settings import OUTPUT_DIR


# Frozen implementations. Do not change these weights after viewing results.
IMPLEMENTATIONS = {
    "AMZN": {
        "components": {"AMZN": 1.00},
        "primary_sample": "Full_available_history",
    },
    "WMT": {
        "components": {"WMT": 1.00},
        "primary_sample": "Validation_2019_2025",
    },
    "ETSY": {
        "components": {"ETSY": 1.00},
        "primary_sample": "Validation_2019_2025",
    },
    "Portfolio_AMZN50_WMT50": {
        "components": {
            "AMZN": 0.50,
            "WMT": 0.50,
        },
        "primary_sample": "Full_available_history",
    },
    "Portfolio_AMZN40_WMT40_ETSY20": {
        "components": {
            "AMZN": 0.40,
            "WMT": 0.40,
            "ETSY": 0.20,
        },
        "primary_sample": "Validation_2019_2025",
    },
}

# Exact event-panel rows used for each stock. The stock return itself does not
# depend on the factor model, but filtering the frozen model prevents duplicates.
COMPONENT_MODELS = {
    "AMZN": ("AMZN_vs_SPY_XRT", "SPY_XRT"),
    "WMT": ("WMT_vs_SPY_XRT", "SPY_XRT"),
    "ETSY": ("ETSY_vs_SPY_XRT", "SPY_XRT"),
}

ENTRY_RELATIVE_DAY = -4
RETURN_START_DAY = -3
EXIT_RELATIVE_DAY = 1
RETURN_DAYS = list(range(RETURN_START_DAY, EXIT_RELATIVE_DAY + 1))
COST_LEVELS_BPS = [25, 50]

SAMPLE_NAMES = [
    "Full_available_history",
    "Discovery_2010_2018",
    "Validation_2019_2025",
]

# Frozen paired comparisons.
PAIRED_COMPARISONS = [
    {
        "comparison": "Portfolio50_versus_AMZN",
        "left": "Portfolio_AMZN50_WMT50",
        "right": "AMZN",
        "samples": ["Full_available_history", "Validation_2019_2025"],
    },
    {
        "comparison": "Portfolio50_versus_WMT",
        "left": "Portfolio_AMZN50_WMT50",
        "right": "WMT",
        "samples": ["Full_available_history", "Validation_2019_2025"],
    },
    {
        "comparison": "Portfolio40_40_20_versus_Portfolio50",
        "left": "Portfolio_AMZN40_WMT40_ETSY20",
        "right": "Portfolio_AMZN50_WMT50",
        "samples": ["Validation_2019_2025"],
    },
]

BOOTSTRAP_ITERATIONS = 30_000
BOOTSTRAP_CONFIDENCE = 0.95
BASE_RANDOM_SEED = 20260722


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


def _downside_deviation(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan
    downside = np.minimum(values, 0.0)
    return float(np.sqrt(np.mean(np.square(downside))))


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
    means = resampled.mean(axis=1)
    alpha = 1.0 - confidence
    return (
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def _two_sided_paired_tests(values: np.ndarray) -> tuple[float, float, float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return np.nan, np.nan, np.nan, np.nan

    t_result = stats.ttest_1samp(values, popmean=0.0, nan_policy="omit")

    nonzero = values[~np.isclose(values, 0.0)]
    if len(nonzero) < 2:
        wilcoxon_stat = np.nan
        wilcoxon_p = np.nan
    else:
        try:
            wilcoxon_result = stats.wilcoxon(
                nonzero,
                alternative="two-sided",
                zero_method="wilcox",
                method="auto",
            )
            wilcoxon_stat = float(wilcoxon_result.statistic)
            wilcoxon_p = float(wilcoxon_result.pvalue)
        except ValueError:
            wilcoxon_stat = np.nan
            wilcoxon_p = np.nan

    return (
        float(t_result.statistic),
        float(t_result.pvalue),
        wilcoxon_stat,
        wilcoxon_p,
    )


def _prepare_adjusted_open(prices: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    prices = prices.copy()

    if "adjusted_open" in prices.columns:
        prices["risk_adjusted_open"] = pd.to_numeric(
            prices["adjusted_open"], errors="coerce"
        )
        return prices, "adjusted_open"

    if {"open", "close", "adjusted_close"}.issubset(prices.columns):
        open_values = pd.to_numeric(prices["open"], errors="coerce")
        close_values = pd.to_numeric(prices["close"], errors="coerce")
        adjusted_close = pd.to_numeric(prices["adjusted_close"], errors="coerce")
        valid_close = close_values.replace(0.0, np.nan)
        prices["risk_adjusted_open"] = open_values * adjusted_close / valid_close
        return prices, "derived_from_open_close_adjusted_close"

    prices["risk_adjusted_open"] = np.nan
    return prices, "unavailable"


def _prepare_component_daily(panel: pd.DataFrame) -> pd.DataFrame:
    required = {
        "ticker",
        "model_name",
        "event_year",
        "relative_day",
        "date",
        "stock_return",
    }
    missing = required - set(panel.columns)
    if missing:
        raise RuntimeError(
            "event_panel is missing columns: " + ", ".join(sorted(missing))
        )

    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel["event_year"] = panel["event_year"].astype(int)
    panel["relative_day"] = panel["relative_day"].astype(int)
    panel["stock_return"] = pd.to_numeric(panel["stock_return"], errors="coerce")

    rows: list[pd.DataFrame] = []
    for ticker, (_, model_name) in COMPONENT_MODELS.items():
        selected = panel[
            panel["ticker"].eq(ticker)
            & panel["model_name"].eq(model_name)
            & panel["relative_day"].between(
                ENTRY_RELATIVE_DAY, EXIT_RELATIVE_DAY
            )
        ].copy()
        selected["component"] = ticker
        rows.append(selected)

    combined = pd.concat(rows, ignore_index=True)
    duplicate_counts = (
        combined.groupby(["component", "event_year", "relative_day"])
        .size()
        .reset_index(name="row_count")
    )
    duplicates = duplicate_counts[duplicate_counts["row_count"] > 1]
    if not duplicates.empty:
        raise RuntimeError("Duplicate component/day rows found in event_panel.")

    return combined


def _prepare_trade_lookup(
    validation_trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {
        "implementation",
        "trade_type",
        "cost_bps",
        "event_year",
        "entry_date",
        "exit_date",
        "gross_return",
        "transaction_cost",
        "net_return",
    }
    missing = required - set(validation_trades.columns)
    if missing:
        raise RuntimeError(
            "execution_validation_trades is missing columns: "
            + ", ".join(sorted(missing))
        )

    trades = validation_trades.copy()
    trades["event_year"] = trades["event_year"].astype(int)
    trades["cost_bps"] = trades["cost_bps"].astype(int)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    trades["exit_date"] = pd.to_datetime(trades["exit_date"])

    long_only = trades[
        trades["trade_type"].eq("LongOnly")
        & trades["cost_bps"].isin(COST_LEVELS_BPS)
    ].copy()

    component_names = ["AMZN", "WMT", "ETSY"]
    component_trades = long_only[
        long_only["implementation"].isin(component_names)
    ].copy()

    return long_only, component_trades


def _build_component_price_lookup(
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    required = {"ticker", "date", "adjusted_close"}
    missing = required - set(prices.columns)
    if missing:
        raise RuntimeError(
            "daily_prices is missing columns: " + ", ".join(sorted(missing))
        )

    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices["adjusted_close"] = pd.to_numeric(
        prices["adjusted_close"], errors="coerce"
    )
    prices, open_source = _prepare_adjusted_open(prices)
    prices = prices[prices["ticker"].isin(COMPONENT_MODELS)].copy()
    prices = prices.drop_duplicates(["ticker", "date"])
    return prices, open_source


def _component_path_for_year(
    daily: pd.DataFrame,
    prices: pd.DataFrame,
    ticker: str,
    event_year: int,
) -> pd.DataFrame:
    year_daily = daily[
        daily["component"].eq(ticker)
        & daily["event_year"].eq(event_year)
    ].sort_values("relative_day")

    expected_days = set(range(ENTRY_RELATIVE_DAY, EXIT_RELATIVE_DAY + 1))
    actual_days = set(year_daily["relative_day"].astype(int))
    if not expected_days.issubset(actual_days):
        return pd.DataFrame()

    year_daily = year_daily[
        year_daily["relative_day"].between(
            ENTRY_RELATIVE_DAY, EXIT_RELATIVE_DAY
        )
    ].copy()

    merged = year_daily.merge(
        prices[
            ["ticker", "date", "adjusted_close", "risk_adjusted_open"]
        ],
        left_on=["component", "date"],
        right_on=["ticker", "date"],
        how="left",
        validate="one_to_one",
    )

    entry_row = merged[merged["relative_day"].eq(ENTRY_RELATIVE_DAY)]
    if entry_row.empty:
        return pd.DataFrame()

    entry_price = float(entry_row["adjusted_close"].iloc[0])
    if not np.isfinite(entry_price) or entry_price <= 0:
        return pd.DataFrame()

    output = merged[merged["relative_day"].isin(RETURN_DAYS)].copy()
    output = output.sort_values("relative_day")
    if len(output) != len(RETURN_DAYS):
        return pd.DataFrame()

    output["component_cumulative_gross_return"] = (
        output["adjusted_close"] / entry_price - 1.0
    )
    output["component_wealth"] = (
        1.0 + output["component_cumulative_gross_return"]
    )

    previous_close = merged[
        ["relative_day", "adjusted_close"]
    ].copy()
    previous_close["relative_day"] = previous_close["relative_day"] + 1
    previous_close = previous_close.rename(
        columns={"adjusted_close": "previous_adjusted_close"}
    )
    output = output.merge(
        previous_close,
        on="relative_day",
        how="left",
        validate="one_to_one",
    )

    output["overnight_return"] = (
        output["risk_adjusted_open"] / output["previous_adjusted_close"] - 1.0
    )
    output["intraday_return"] = (
        output["adjusted_close"] / output["risk_adjusted_open"] - 1.0
    )

    output["component"] = ticker
    output["event_year"] = event_year
    return output


def _build_paths_and_risk(
    daily: pd.DataFrame,
    prices: pd.DataFrame,
    implementation_trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    path_rows: list[dict] = []
    annual_rows: list[dict] = []
    contribution_rows: list[dict] = []
    diagnostics: list[dict] = []

    for implementation, definition in IMPLEMENTATIONS.items():
        weights: dict[str, float] = definition["components"]
        weight_sum = float(sum(weights.values()))
        if not np.isclose(weight_sum, 1.0):
            raise ValueError(
                f"Weights for {implementation} sum to {weight_sum}, not 1.0."
            )

        implementation_source = implementation_trades[
            implementation_trades["implementation"].eq(implementation)
        ]

        for cost_bps in COST_LEVELS_BPS:
            cost_source = implementation_source[
                implementation_source["cost_bps"].eq(cost_bps)
            ].sort_values("event_year")

            for source_row in cost_source.itertuples(index=False):
                event_year = int(source_row.event_year)
                component_paths: dict[str, pd.DataFrame] = {}
                missing_components: list[str] = []

                for ticker in weights:
                    component_path = _component_path_for_year(
                        daily=daily,
                        prices=prices,
                        ticker=ticker,
                        event_year=event_year,
                    )
                    if component_path.empty:
                        missing_components.append(ticker)
                    else:
                        component_paths[ticker] = component_path

                if missing_components:
                    diagnostics.append(
                        {
                            "implementation": implementation,
                            "cost_bps": cost_bps,
                            "event_year": event_year,
                            "status": "component_path_missing",
                            "detail": ",".join(missing_components),
                        }
                    )
                    continue

                date_sets = {
                    ticker: tuple(
                        path.sort_values("relative_day")["date"].dt.strftime(
                            "%Y-%m-%d"
                        )
                    )
                    for ticker, path in component_paths.items()
                }
                if len(set(date_sets.values())) != 1:
                    diagnostics.append(
                        {
                            "implementation": implementation,
                            "cost_bps": cost_bps,
                            "event_year": event_year,
                            "status": "component_date_mismatch",
                            "detail": str(date_sets),
                        }
                    )
                    continue

                path_frame = pd.DataFrame(
                    {
                        "relative_day": RETURN_DAYS,
                        "date": next(iter(component_paths.values()))[
                            "date"
                        ].to_numpy(),
                    }
                )

                portfolio_wealth = np.zeros(len(path_frame), dtype=float)
                portfolio_open_wealth = np.zeros(len(path_frame), dtype=float)
                open_available = True

                for ticker, weight in weights.items():
                    component_path = component_paths[ticker].sort_values(
                        "relative_day"
                    )
                    wealth = component_path["component_wealth"].to_numpy(
                        dtype=float
                    )
                    portfolio_wealth += weight * wealth

                    entry_price = float(
                        component_path["adjusted_close"].iloc[0]
                        / wealth[0]
                    )
                    adjusted_open = component_path["risk_adjusted_open"].to_numpy(
                        dtype=float
                    )
                    if np.all(np.isfinite(adjusted_open)):
                        portfolio_open_wealth += weight * adjusted_open / entry_price
                    else:
                        open_available = False

                cumulative_gross = portfolio_wealth - 1.0
                transaction_cost = float(source_row.transaction_cost)
                cumulative_net = cumulative_gross - transaction_cost

                previous_close_wealth = np.concatenate(
                    ([1.0], portfolio_wealth[:-1])
                )
                daily_returns = portfolio_wealth / previous_close_wealth - 1.0

                if open_available:
                    overnight_returns = (
                        portfolio_open_wealth / previous_close_wealth - 1.0
                    )
                    intraday_returns = (
                        portfolio_wealth / portfolio_open_wealth - 1.0
                    )
                else:
                    overnight_returns = np.full(len(path_frame), np.nan)
                    intraday_returns = np.full(len(path_frame), np.nan)

                mae_index = int(np.argmin(cumulative_net))
                mfe_index = int(np.argmax(cumulative_net))
                worst_day_index = int(np.argmin(daily_returns))
                best_day_index = int(np.argmax(daily_returns))

                if open_available:
                    worst_overnight_index = int(np.argmin(overnight_returns))
                    best_overnight_index = int(np.argmax(overnight_returns))
                    worst_intraday_index = int(np.argmin(intraday_returns))
                    best_intraday_index = int(np.argmax(intraday_returns))
                else:
                    worst_overnight_index = best_overnight_index = -1
                    worst_intraday_index = best_intraday_index = -1

                reconstructed_gross = float(cumulative_gross[-1])
                reconstructed_net = float(cumulative_net[-1])
                gross_error = reconstructed_gross - float(source_row.gross_return)
                net_error = reconstructed_net - float(source_row.net_return)

                annual_rows.append(
                    {
                        "implementation": implementation,
                        "primary_sample": definition["primary_sample"],
                        "cost_bps": cost_bps,
                        "event_year": event_year,
                        "entry_date": pd.Timestamp(source_row.entry_date),
                        "exit_date": pd.Timestamp(source_row.exit_date),
                        "net_return": float(source_row.net_return),
                        "gross_return": float(source_row.gross_return),
                        "transaction_cost": transaction_cost,
                        "close_to_close_mae_net": float(cumulative_net[mae_index]),
                        "mae_relative_day": int(
                            path_frame.loc[mae_index, "relative_day"]
                        ),
                        "mae_date": pd.Timestamp(path_frame.loc[mae_index, "date"]),
                        "close_to_close_mfe_net": float(cumulative_net[mfe_index]),
                        "mfe_relative_day": int(
                            path_frame.loc[mfe_index, "relative_day"]
                        ),
                        "mfe_date": pd.Timestamp(path_frame.loc[mfe_index, "date"]),
                        "worst_daily_return": float(daily_returns[worst_day_index]),
                        "worst_daily_relative_day": int(
                            path_frame.loc[worst_day_index, "relative_day"]
                        ),
                        "worst_daily_date": pd.Timestamp(
                            path_frame.loc[worst_day_index, "date"]
                        ),
                        "best_daily_return": float(daily_returns[best_day_index]),
                        "best_daily_relative_day": int(
                            path_frame.loc[best_day_index, "relative_day"]
                        ),
                        "best_daily_date": pd.Timestamp(
                            path_frame.loc[best_day_index, "date"]
                        ),
                        "open_data_available": open_available,
                        "worst_overnight_return": (
                            float(overnight_returns[worst_overnight_index])
                            if open_available
                            else np.nan
                        ),
                        "worst_overnight_relative_day": (
                            int(
                                path_frame.loc[
                                    worst_overnight_index, "relative_day"
                                ]
                            )
                            if open_available
                            else np.nan
                        ),
                        "best_overnight_return": (
                            float(overnight_returns[best_overnight_index])
                            if open_available
                            else np.nan
                        ),
                        "worst_intraday_return": (
                            float(intraday_returns[worst_intraday_index])
                            if open_available
                            else np.nan
                        ),
                        "worst_intraday_relative_day": (
                            int(
                                path_frame.loc[
                                    worst_intraday_index, "relative_day"
                                ]
                            )
                            if open_available
                            else np.nan
                        ),
                        "best_intraday_return": (
                            float(intraday_returns[best_intraday_index])
                            if open_available
                            else np.nan
                        ),
                        "gross_reconstruction_error": gross_error,
                        "net_reconstruction_error": net_error,
                    }
                )

                for position, base_row in path_frame.iterrows():
                    path_rows.append(
                        {
                            "implementation": implementation,
                            "cost_bps": cost_bps,
                            "event_year": event_year,
                            "relative_day": int(base_row.relative_day),
                            "date": pd.Timestamp(base_row.date),
                            "daily_portfolio_return": float(
                                daily_returns[position]
                            ),
                            "gross_cumulative_return": float(
                                cumulative_gross[position]
                            ),
                            "net_cumulative_return": float(
                                cumulative_net[position]
                            ),
                            "overnight_return": (
                                float(overnight_returns[position])
                                if open_available
                                else np.nan
                            ),
                            "intraday_return": (
                                float(intraday_returns[position])
                                if open_available
                                else np.nan
                            ),
                            "open_data_available": open_available,
                        }
                    )

                for ticker, weight in weights.items():
                    component_trade = implementation_trades[
                        implementation_trades["implementation"].eq(ticker)
                        & implementation_trades["cost_bps"].eq(cost_bps)
                        & implementation_trades["event_year"].eq(event_year)
                    ]
                    if component_trade.empty:
                        diagnostics.append(
                            {
                                "implementation": implementation,
                                "cost_bps": cost_bps,
                                "event_year": event_year,
                                "status": "component_trade_missing",
                                "detail": ticker,
                            }
                        )
                        continue

                    component_trade_row = component_trade.iloc[0]
                    contribution_rows.append(
                        {
                            "implementation": implementation,
                            "cost_bps": cost_bps,
                            "event_year": event_year,
                            "component": ticker,
                            "weight": weight,
                            "component_gross_return": float(
                                component_trade_row["gross_return"]
                            ),
                            "component_transaction_cost": float(
                                component_trade_row["transaction_cost"]
                            ),
                            "component_net_return": float(
                                component_trade_row["net_return"]
                            ),
                            "gross_return_contribution": float(
                                weight * component_trade_row["gross_return"]
                            ),
                            "cost_contribution": float(
                                weight * component_trade_row["transaction_cost"]
                            ),
                            "net_return_contribution": float(
                                weight * component_trade_row["net_return"]
                            ),
                            "portfolio_net_return": float(source_row.net_return),
                            "share_of_portfolio_net_return": (
                                float(
                                    weight
                                    * component_trade_row["net_return"]
                                    / source_row.net_return
                                )
                                if not np.isclose(source_row.net_return, 0.0)
                                else np.nan
                            ),
                        }
                    )

                status = "ok"
                detail = ""
                if abs(gross_error) > 1e-8 or abs(net_error) > 1e-8:
                    status = "return_reconstruction_mismatch"
                    detail = (
                        f"gross_error={gross_error:.3e};"
                        f"net_error={net_error:.3e}"
                    )

                diagnostics.append(
                    {
                        "implementation": implementation,
                        "cost_bps": cost_bps,
                        "event_year": event_year,
                        "status": status,
                        "detail": detail,
                    }
                )

    return (
        pd.DataFrame(path_rows),
        pd.DataFrame(annual_rows),
        pd.DataFrame(contribution_rows),
        pd.DataFrame(diagnostics),
    )


def _summarize_risk(annual: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []

    for (implementation, cost_bps), group in annual.groupby(
        ["implementation", "cost_bps"], sort=False
    ):
        primary_sample = str(group["primary_sample"].iloc[0])

        for sample in SAMPLE_NAMES:
            sample_data = group.loc[_sample_mask(group, sample)].sort_values(
                "event_year"
            )
            if sample_data.empty:
                continue

            returns = sample_data["net_return"].to_numpy(dtype=float)
            maes = sample_data["close_to_close_mae_net"].to_numpy(dtype=float)
            mfes = sample_data["close_to_close_mfe_net"].to_numpy(dtype=float)
            worst_days = sample_data["worst_daily_return"].to_numpy(dtype=float)

            worst_trade_index = int(np.argmin(returns))
            worst_mae_index = int(np.argmin(maes))
            worst_day_index = int(np.argmin(worst_days))

            open_rows = sample_data[sample_data["open_data_available"].astype(bool)]

            rows.append(
                {
                    "implementation": implementation,
                    "primary_sample": primary_sample,
                    "is_primary_sample": sample == primary_sample,
                    "cost_bps": int(cost_bps),
                    "sample": sample,
                    "n_trades": len(sample_data),
                    "mean_return": float(np.mean(returns)),
                    "median_return": float(np.median(returns)),
                    "positive_rate": float(np.mean(returns > 0)),
                    "worst_return": float(returns[worst_trade_index]),
                    "worst_return_year": int(
                        sample_data.iloc[worst_trade_index]["event_year"]
                    ),
                    "cumulative_return": float(np.prod(1.0 + returns) - 1.0),
                    "annual_sequence_max_drawdown": _max_drawdown(returns),
                    "downside_deviation": _downside_deviation(returns),
                    "mean_close_to_close_mae_net": float(np.mean(maes)),
                    "median_close_to_close_mae_net": float(np.median(maes)),
                    "worst_close_to_close_mae_net": float(maes[worst_mae_index]),
                    "worst_mae_year": int(
                        sample_data.iloc[worst_mae_index]["event_year"]
                    ),
                    "worst_mae_relative_day": int(
                        sample_data.iloc[worst_mae_index]["mae_relative_day"]
                    ),
                    "mean_close_to_close_mfe_net": float(np.mean(mfes)),
                    "median_close_to_close_mfe_net": float(np.median(mfes)),
                    "average_worst_daily_return": float(np.mean(worst_days)),
                    "worst_single_daily_return": float(worst_days[worst_day_index]),
                    "worst_single_daily_year": int(
                        sample_data.iloc[worst_day_index]["event_year"]
                    ),
                    "worst_single_daily_relative_day": int(
                        sample_data.iloc[worst_day_index][
                            "worst_daily_relative_day"
                        ]
                    ),
                    "open_data_years": len(open_rows),
                    "worst_overnight_return": (
                        float(open_rows["worst_overnight_return"].min())
                        if not open_rows.empty
                        else np.nan
                    ),
                    "worst_intraday_return": (
                        float(open_rows["worst_intraday_return"].min())
                        if not open_rows.empty
                        else np.nan
                    ),
                }
            )

    return pd.DataFrame(rows)


def _summarize_contributions(contributions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []

    for (implementation, cost_bps, component), group in contributions.groupby(
        ["implementation", "cost_bps", "component"], sort=False
    ):
        for sample in SAMPLE_NAMES:
            sample_data = group.loc[_sample_mask(group, sample)]
            if sample_data.empty:
                continue

            component_values = sample_data["net_return_contribution"].to_numpy(
                dtype=float
            )
            portfolio_values = sample_data["portfolio_net_return"].to_numpy(
                dtype=float
            )
            portfolio_mean = float(np.mean(portfolio_values))
            mean_contribution = float(np.mean(component_values))

            rows.append(
                {
                    "implementation": implementation,
                    "cost_bps": int(cost_bps),
                    "sample": sample,
                    "component": component,
                    "weight": float(sample_data["weight"].iloc[0]),
                    "n_years": len(sample_data),
                    "mean_net_return_contribution": mean_contribution,
                    "median_net_return_contribution": float(
                        np.median(component_values)
                    ),
                    "positive_contribution_rate": float(
                        np.mean(component_values > 0)
                    ),
                    "worst_contribution": float(np.min(component_values)),
                    "best_contribution": float(np.max(component_values)),
                    "mean_portfolio_return": portfolio_mean,
                    "share_of_mean_portfolio_return": (
                        mean_contribution / portfolio_mean
                        if not np.isclose(portfolio_mean, 0.0)
                        else np.nan
                    ),
                }
            )

    return pd.DataFrame(rows)


def _build_correlations(
    implementation_trades: pd.DataFrame,
    component_daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    components = ["AMZN", "WMT", "ETSY"]

    individual_trades = implementation_trades[
        implementation_trades["implementation"].isin(components)
    ].copy()

    for cost_bps in COST_LEVELS_BPS:
        cost_data = individual_trades[individual_trades["cost_bps"].eq(cost_bps)]
        pivot = cost_data.pivot_table(
            index="event_year",
            columns="implementation",
            values="net_return",
            aggfunc="first",
        ).reset_index()

        for sample in SAMPLE_NAMES:
            sample_data = pivot.loc[_sample_mask(pivot, sample)]

            for left, right in combinations(components, 2):
                pair = sample_data[[left, right]].dropna()
                if len(pair) < 2:
                    pearson = spearman = covariance = np.nan
                else:
                    pearson = float(pair[left].corr(pair[right], method="pearson"))
                    spearman = float(pair[left].corr(pair[right], method="spearman"))
                    covariance = float(pair[[left, right]].cov().iloc[0, 1])

                rows.append(
                    {
                        "correlation_type": "annual_trade_net_return",
                        "cost_bps": cost_bps,
                        "sample": sample,
                        "left_component": left,
                        "right_component": right,
                        "n_observations": len(pair),
                        "pearson_correlation": pearson,
                        "spearman_correlation": spearman,
                        "covariance": covariance,
                    }
                )

    daily_returns = component_daily[
        component_daily["relative_day"].isin(RETURN_DAYS)
    ][
        ["event_year", "relative_day", "component", "stock_return"]
    ].copy()
    daily_pivot = daily_returns.pivot_table(
        index=["event_year", "relative_day"],
        columns="component",
        values="stock_return",
        aggfunc="first",
    ).reset_index()

    for sample in SAMPLE_NAMES:
        sample_data = daily_pivot.loc[_sample_mask(daily_pivot, sample)]
        for left, right in combinations(components, 2):
            pair = sample_data[[left, right]].dropna()
            if len(pair) < 2:
                pearson = spearman = covariance = np.nan
            else:
                pearson = float(pair[left].corr(pair[right], method="pearson"))
                spearman = float(pair[left].corr(pair[right], method="spearman"))
                covariance = float(pair[[left, right]].cov().iloc[0, 1])

            rows.append(
                {
                    "correlation_type": "pooled_daily_event_return",
                    "cost_bps": np.nan,
                    "sample": sample,
                    "left_component": left,
                    "right_component": right,
                    "n_observations": len(pair),
                    "pearson_correlation": pearson,
                    "spearman_correlation": spearman,
                    "covariance": covariance,
                }
            )

    return pd.DataFrame(rows)


def _build_paired_comparisons(
    implementation_trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_rows: list[dict] = []
    summary_rows: list[dict] = []
    analysis_counter = 0

    for comparison_definition in PAIRED_COMPARISONS:
        comparison = comparison_definition["comparison"]
        left = comparison_definition["left"]
        right = comparison_definition["right"]

        for cost_bps in COST_LEVELS_BPS:
            source = implementation_trades[
                implementation_trades["implementation"].isin([left, right])
                & implementation_trades["cost_bps"].eq(cost_bps)
            ]
            pivot = source.pivot_table(
                index="event_year",
                columns="implementation",
                values="net_return",
                aggfunc="first",
            ).dropna(subset=[left, right])

            if pivot.empty:
                continue

            pivot = pivot.reset_index()
            pivot["return_difference"] = pivot[left] - pivot[right]

            for row in pivot.itertuples(index=False):
                pair_rows.append(
                    {
                        "comparison": comparison,
                        "left_implementation": left,
                        "right_implementation": right,
                        "cost_bps": cost_bps,
                        "event_year": int(row.event_year),
                        "left_return": float(getattr(row, left)),
                        "right_return": float(getattr(row, right)),
                        "left_minus_right": float(row.return_difference),
                        "left_beats_right": bool(row.return_difference > 0),
                    }
                )

            for sample in comparison_definition["samples"]:
                sample_data = pivot.loc[_sample_mask(pivot, sample)].copy()
                if sample_data.empty:
                    continue

                differences = sample_data["return_difference"].to_numpy(dtype=float)
                left_returns = sample_data[left].to_numpy(dtype=float)
                right_returns = sample_data[right].to_numpy(dtype=float)
                analysis_counter += 1
                ci_low, ci_high = _bootstrap_mean_ci(
                    differences,
                    seed=BASE_RANDOM_SEED + 200_000 + analysis_counter,
                )
                t_stat, t_p, wilcoxon_stat, wilcoxon_p = _two_sided_paired_tests(
                    differences
                )

                summary_rows.append(
                    {
                        "comparison": comparison,
                        "left_implementation": left,
                        "right_implementation": right,
                        "cost_bps": cost_bps,
                        "sample": sample,
                        "n_pairs": len(sample_data),
                        "left_mean_return": float(np.mean(left_returns)),
                        "right_mean_return": float(np.mean(right_returns)),
                        "mean_left_minus_right": float(np.mean(differences)),
                        "median_left_minus_right": float(np.median(differences)),
                        "left_beats_right_rate": float(np.mean(differences > 0)),
                        "difference_bootstrap_95_low": ci_low,
                        "difference_bootstrap_95_high": ci_high,
                        "left_worst_return": float(np.min(left_returns)),
                        "right_worst_return": float(np.min(right_returns)),
                        "worst_return_improvement": float(
                            np.min(left_returns) - np.min(right_returns)
                        ),
                        "left_downside_deviation": _downside_deviation(left_returns),
                        "right_downside_deviation": _downside_deviation(right_returns),
                        "left_max_drawdown": _max_drawdown(left_returns),
                        "right_max_drawdown": _max_drawdown(right_returns),
                        "difference_t_stat": t_stat,
                        "difference_t_p_two_sided": t_p,
                        "difference_wilcoxon_stat": wilcoxon_stat,
                        "difference_wilcoxon_p_two_sided": wilcoxon_p,
                        "small_sample_warning": len(sample_data) < 8,
                    }
                )

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary["difference_t_p_two_sided_fdr"] = np.nan
        summary["difference_wilcoxon_p_two_sided_fdr"] = np.nan

        for (cost_bps, sample), group in summary.groupby(
            ["cost_bps", "sample"], dropna=False
        ):
            for source_column, target_column in [
                ("difference_t_p_two_sided", "difference_t_p_two_sided_fdr"),
                (
                    "difference_wilcoxon_p_two_sided",
                    "difference_wilcoxon_p_two_sided_fdr",
                ),
            ]:
                valid = group[group[source_column].notna()]
                if valid.empty:
                    continue
                _, adjusted, _, _ = multipletests(
                    valid[source_column].astype(float),
                    alpha=0.05,
                    method="fdr_bh",
                )
                summary.loc[valid.index, target_column] = adjusted

    return pd.DataFrame(pair_rows), summary


def run_implementation_risk_analysis() -> dict[str, pd.DataFrame]:
    event_panel = read_table("event_panel")
    daily_prices = read_table("daily_prices")
    validation_trades = read_table("execution_validation_trades")

    component_daily = _prepare_component_daily(event_panel)
    prices, open_source = _build_component_price_lookup(daily_prices)
    implementation_trades, _ = _prepare_trade_lookup(validation_trades)

    paths, annual_risk, contributions, diagnostics = _build_paths_and_risk(
        daily=component_daily,
        prices=prices,
        implementation_trades=implementation_trades,
    )

    if annual_risk.empty:
        raise RuntimeError("No implementation-risk rows were created.")

    risk_summary = _summarize_risk(annual_risk)
    contribution_summary = _summarize_contributions(contributions)
    correlations = _build_correlations(
        implementation_trades=implementation_trades,
        component_daily=component_daily,
    )
    comparison_pairs, comparison_summary = _build_paired_comparisons(
        implementation_trades=implementation_trades,
    )

    metadata = pd.DataFrame(
        [
            {
                "analysis": "implementation_risk_analysis",
                "entry_relative_day": ENTRY_RELATIVE_DAY,
                "return_start_day": RETURN_START_DAY,
                "exit_relative_day": EXIT_RELATIVE_DAY,
                "open_price_source": open_source,
                "mae_mfe_definition": (
                    "Close-to-close cumulative return; complete round-trip cost "
                    "deducted throughout path so final value reconciles to net return."
                ),
                "portfolio_definition": (
                    "Fixed initial weights; no rebalancing during the five return days."
                ),
            }
        ]
    )

    for dataframe, columns in [
        (paths, ["implementation", "cost_bps", "event_year", "relative_day"]),
        (annual_risk, ["implementation", "cost_bps", "event_year"]),
        (
            contributions,
            ["implementation", "cost_bps", "event_year", "component"],
        ),
        (
            risk_summary,
            ["implementation", "cost_bps", "sample"],
        ),
        (
            contribution_summary,
            ["implementation", "cost_bps", "sample", "component"],
        ),
        (
            correlations,
            [
                "correlation_type",
                "cost_bps",
                "sample",
                "left_component",
                "right_component",
            ],
        ),
        (
            comparison_pairs,
            ["comparison", "cost_bps", "event_year"],
        ),
        (
            comparison_summary,
            ["comparison", "cost_bps", "sample"],
        ),
        (diagnostics, ["implementation", "cost_bps", "event_year", "status"]),
    ]:
        if not dataframe.empty:
            dataframe.sort_values(columns, inplace=True, ignore_index=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "implementation_risk_paths": paths,
        "implementation_risk_annual": annual_risk,
        "implementation_risk_summary": risk_summary,
        "implementation_component_contributions": contributions,
        "implementation_component_contribution_summary": contribution_summary,
        "implementation_event_correlations": correlations,
        "implementation_comparison_pairs": comparison_pairs,
        "implementation_comparison_summary": comparison_summary,
        "implementation_risk_diagnostics": diagnostics,
        "implementation_risk_metadata": metadata,
    }

    for name, dataframe in outputs.items():
        dataframe.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        write_table(dataframe, name)

    ok_count = int((diagnostics["status"] == "ok").sum())
    error_count = int((diagnostics["status"] != "ok").sum())

    print("Implementation-risk analysis completed.")
    print(
        f"Created {len(annual_risk)} annual risk rows, "
        f"{len(paths)} path rows, and "
        f"{len(comparison_summary)} paired-comparison summary rows."
    )
    print(f"Diagnostics: {ok_count} ok rows and {error_count} error rows.")
    print(f"Open-price source: {open_source}.")

    return outputs


if __name__ == "__main__":
    run_implementation_risk_analysis()
