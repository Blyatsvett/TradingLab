from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_UNIVERSE_PATH = (
    PROJECT_ROOT / "config" / "labor_day_universe.csv"
)
DEFAULT_PANEL_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_universe_by_year.csv"
)
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "labor_day_universe_manifest.json"
)

STUDY_START_YEAR = 1998
DISCOVERY_END_YEAR = 2014
VALIDATION_START_YEAR = 2015
VALIDATION_END_YEAR = 2025
FORWARD_YEAR = 2026

EXPECTED_COLUMNS = [
    "ticker",
    "provider_symbol",
    "instrument_name",
    "hypothesis",
    "subindustry",
    "role",
    "analysis_tier",
    "security_type",
    "exchange",
    "currency",
    "primary_benchmark",
    "fallback_benchmark",
    "analysis_start_year",
    "analysis_end_year",
    "discovery_eligible",
    "validation_eligible",
    "forward_eligible",
    "continuity_status",
    "predecessor_symbols",
    "source_url",
    "notes",
]

PANEL_COLUMNS = [
    "event_year",
    "sample",
    "ticker",
    "provider_symbol",
    "instrument_name",
    "hypothesis",
    "subindustry",
    "role",
    "analysis_tier",
    "resolved_benchmark",
    "benchmark_resolution",
    "eligible_group_members",
    "equal_weight",
    "continuity_status",
]

TARGET_HYPOTHESES = {
    "refining_gasoline",
    "auto_dealers",
    "domestic_leisure_travel",
}
ALLOWED_HYPOTHESES = TARGET_HYPOTHESES | {"generic_control"}
ALLOWED_ROLES = {
    "market_benchmark",
    "sector_benchmark",
    "negative_control",
    "size_control",
    "hypothesis_stock",
}
ALLOWED_ANALYSIS_TIERS = {"core", "extension"}
ALLOWED_SECURITY_TYPES = {"etf", "common_stock"}
ALLOWED_EXCHANGES = {"NYSE", "NASDAQ", "NYSE_ARCA"}
ALLOWED_CONTINUITY = {
    "continuous",
    "predecessor_continuity",
    "current_public_era",
}
BOOLEAN_COLUMNS = [
    "discovery_eligible",
    "validation_eligible",
    "forward_eligible",
]

TICKER_PATTERN = r"[A-Z][A-Z0-9.\-]*"


class UniverseValidationError(ValueError):
    """Raised when the frozen universe violates its data contract."""


@dataclass(frozen=True)
class UniverseBuildResult:
    universe: pd.DataFrame
    panel: pd.DataFrame
    manifest: dict[str, object]


def sample_for_year(year: int) -> str:
    if STUDY_START_YEAR <= year <= DISCOVERY_END_YEAR:
        return "discovery"
    if VALIDATION_START_YEAR <= year <= VALIDATION_END_YEAR:
        return "validation"
    if year == FORWARD_YEAR:
        return "forward"
    raise ValueError(
        "Year is outside the frozen Labor Day samples: "
        f"{year}"
    )


def sample_flag_for_year(year: int) -> str:
    sample = sample_for_year(year)
    return {
        "discovery": "discovery_eligible",
        "validation": "validation_eligible",
        "forward": "forward_eligible",
    }[sample]


def _parse_boolean_column(
    dataframe: pd.DataFrame,
    column: str,
) -> pd.Series:
    values = dataframe[column].astype(str).str.strip().str.lower()
    invalid = sorted(
        value
        for value in values.unique()
        if value not in {"true", "false"}
    )
    if invalid:
        raise UniverseValidationError(
            f"{column} must contain only true/false; "
            f"found {invalid}."
        )
    return values.eq("true")


def _parse_year_column(
    dataframe: pd.DataFrame,
    column: str,
    *,
    allow_blank: bool,
) -> pd.Series:
    values = dataframe[column].astype(str).str.strip()
    if allow_blank:
        invalid_blank_mask = pd.Series(
            False,
            index=dataframe.index,
        )
    else:
        invalid_blank_mask = values.eq("")

    parsed = pd.to_numeric(
        values.replace("", pd.NA),
        errors="coerce",
    ).astype("Int64")

    invalid = invalid_blank_mask | (
        values.ne("") & parsed.isna()
    )
    if invalid.any():
        bad = dataframe.loc[invalid, ["ticker", column]]
        raise UniverseValidationError(
            f"{column} contains invalid values: "
            + bad.to_dict(orient="records").__repr__()
        )
    return parsed


def read_universe(path: Path = DEFAULT_UNIVERSE_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")

    dataframe = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )
    validate_universe(dataframe)
    return normalize_universe(dataframe)


def normalize_universe(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()

    for column in EXPECTED_COLUMNS:
        normalized[column] = (
            normalized[column].astype(str).str.strip()
        )

    normalized["analysis_start_year"] = _parse_year_column(
        normalized,
        "analysis_start_year",
        allow_blank=False,
    )
    normalized["analysis_end_year"] = _parse_year_column(
        normalized,
        "analysis_end_year",
        allow_blank=True,
    )

    for column in BOOLEAN_COLUMNS:
        normalized[column] = _parse_boolean_column(
            normalized,
            column,
        )

    normalized.sort_values(
        [
            "hypothesis",
            "role",
            "analysis_tier",
            "ticker",
        ],
        inplace=True,
    )
    normalized.reset_index(drop=True, inplace=True)
    return normalized


def validate_universe(dataframe: pd.DataFrame) -> None:
    missing = sorted(
        set(EXPECTED_COLUMNS).difference(dataframe.columns)
    )
    extra = sorted(
        set(dataframe.columns).difference(EXPECTED_COLUMNS)
    )
    if missing or extra:
        raise UniverseValidationError(
            "Universe schema mismatch. "
            f"Missing={missing}; extra={extra}"
        )

    frame = dataframe.copy()
    for column in EXPECTED_COLUMNS:
        frame[column] = frame[column].astype(str).str.strip()

    required_text = [
        "ticker",
        "provider_symbol",
        "instrument_name",
        "hypothesis",
        "subindustry",
        "role",
        "analysis_tier",
        "security_type",
        "exchange",
        "currency",
        "continuity_status",
        "source_url",
        "notes",
    ]
    for column in required_text:
        blank = frame[column].eq("")
        if blank.any():
            tickers = frame.loc[blank, "ticker"].tolist()
            raise UniverseValidationError(
                f"{column} is blank for: {tickers}"
            )

    if not frame["ticker"].str.fullmatch(TICKER_PATTERN).all():
        bad = frame.loc[
            ~frame["ticker"].str.fullmatch(TICKER_PATTERN),
            "ticker",
        ].tolist()
        raise UniverseValidationError(
            f"Invalid canonical ticker(s): {bad}"
        )

    if not frame["provider_symbol"].str.fullmatch(
        TICKER_PATTERN
    ).all():
        bad = frame.loc[
            ~frame["provider_symbol"].str.fullmatch(
                TICKER_PATTERN
            ),
            "provider_symbol",
        ].tolist()
        raise UniverseValidationError(
            f"Invalid provider symbol(s): {bad}"
        )

    for column in ["ticker", "provider_symbol"]:
        duplicated = frame.loc[
            frame[column].duplicated(keep=False),
            column,
        ].tolist()
        if duplicated:
            raise UniverseValidationError(
                f"Duplicate {column}(s): "
                + ", ".join(sorted(set(duplicated)))
            )

    allowed_checks = {
        "hypothesis": ALLOWED_HYPOTHESES,
        "role": ALLOWED_ROLES,
        "analysis_tier": ALLOWED_ANALYSIS_TIERS,
        "security_type": ALLOWED_SECURITY_TYPES,
        "exchange": ALLOWED_EXCHANGES,
        "continuity_status": ALLOWED_CONTINUITY,
    }
    for column, allowed in allowed_checks.items():
        invalid = sorted(
            set(frame[column]).difference(allowed)
        )
        if invalid:
            raise UniverseValidationError(
                f"Invalid {column} value(s): {invalid}"
            )

    if not frame["currency"].eq("USD").all():
        bad = frame.loc[
            ~frame["currency"].eq("USD"),
            ["ticker", "currency"],
        ].to_dict(orient="records")
        raise UniverseValidationError(
            f"Universe must be USD-denominated: {bad}"
        )

    if not frame["source_url"].str.startswith("https://").all():
        bad = frame.loc[
            ~frame["source_url"].str.startswith("https://"),
            ["ticker", "source_url"],
        ].to_dict(orient="records")
        raise UniverseValidationError(
            f"source_url must use HTTPS: {bad}"
        )

    start = _parse_year_column(
        frame,
        "analysis_start_year",
        allow_blank=False,
    )
    end = _parse_year_column(
        frame,
        "analysis_end_year",
        allow_blank=True,
    )

    if not start.between(
        STUDY_START_YEAR,
        FORWARD_YEAR,
    ).all():
        bad = frame.loc[
            ~start.between(STUDY_START_YEAR, FORWARD_YEAR),
            ["ticker", "analysis_start_year"],
        ].to_dict(orient="records")
        raise UniverseValidationError(
            f"analysis_start_year is outside study range: {bad}"
        )

    invalid_end = end.notna() & (
        (end < start) | (end > FORWARD_YEAR)
    )
    if invalid_end.any():
        bad = frame.loc[
            invalid_end,
            [
                "ticker",
                "analysis_start_year",
                "analysis_end_year",
            ],
        ].to_dict(orient="records")
        raise UniverseValidationError(
            f"Invalid analysis_end_year: {bad}"
        )

    parsed_flags = {
        column: _parse_boolean_column(frame, column)
        for column in BOOLEAN_COLUMNS
    }

    effective_end = end.fillna(FORWARD_YEAR)
    expected_flags = {
        "discovery_eligible": (
            (start <= DISCOVERY_END_YEAR)
            & (effective_end >= STUDY_START_YEAR)
        ),
        "validation_eligible": (
            (start <= VALIDATION_END_YEAR)
            & (effective_end >= VALIDATION_START_YEAR)
        ),
        "forward_eligible": (
            (start <= FORWARD_YEAR)
            & (effective_end >= FORWARD_YEAR)
        ),
    }
    for column, expected in expected_flags.items():
        mismatch = parsed_flags[column].ne(expected)
        if mismatch.any():
            bad = frame.loc[
                mismatch,
                [
                    "ticker",
                    "analysis_start_year",
                    "analysis_end_year",
                    column,
                ],
            ].to_dict(orient="records")
            raise UniverseValidationError(
                f"{column} conflicts with analysis years: {bad}"
            )

    generic = frame["hypothesis"].eq("generic_control")
    stock_role = frame["role"].eq("hypothesis_stock")

    if not frame.loc[generic, "role"].isin(
        {
            "market_benchmark",
            "sector_benchmark",
            "negative_control",
            "size_control",
        }
    ).all():
        raise UniverseValidationError(
            "generic_control rows may not use hypothesis_stock."
        )

    if not frame.loc[~generic, "role"].eq(
        "hypothesis_stock"
    ).all():
        raise UniverseValidationError(
            "Every target-hypothesis row must be a "
            "hypothesis_stock."
        )

    if not frame.loc[stock_role, "security_type"].eq(
        "common_stock"
    ).all():
        raise UniverseValidationError(
            "hypothesis_stock rows must be common_stock."
        )

    if not frame.loc[generic, "security_type"].eq("etf").all():
        raise UniverseValidationError(
            "All generic controls must be ETFs."
        )

    market = frame.loc[frame["role"].eq("market_benchmark")]
    if len(market) != 1 or market.iloc[0]["ticker"] != "SPY":
        raise UniverseValidationError(
            "SPY must be the unique market_benchmark."
        )
    if (
        market.iloc[0]["primary_benchmark"]
        or market.iloc[0]["fallback_benchmark"]
    ):
        raise UniverseValidationError(
            "The market benchmark may not reference another "
            "benchmark."
        )

    tickers = set(frame["ticker"])
    for column in [
        "primary_benchmark",
        "fallback_benchmark",
    ]:
        references = {
            value
            for value in frame[column]
            if value
        }
        unknown = sorted(references.difference(tickers))
        if unknown:
            raise UniverseValidationError(
                f"Unknown {column} reference(s): {unknown}"
            )

    self_reference = frame.loc[
        frame["ticker"].eq(frame["primary_benchmark"])
        | frame["ticker"].eq(frame["fallback_benchmark"])
    ]
    if not self_reference.empty:
        raise UniverseValidationError(
            "An instrument may not benchmark itself: "
            + ", ".join(self_reference["ticker"])
        )

    expected_primary = {
        "refining_gasoline": "XLE",
        "auto_dealers": "XLY",
        "domestic_leisure_travel": "XLY",
    }
    for hypothesis, benchmark in expected_primary.items():
        subset = frame.loc[
            frame["hypothesis"].eq(hypothesis)
        ]
        if not subset["primary_benchmark"].eq(
            benchmark
        ).all():
            raise UniverseValidationError(
                f"{hypothesis} must use {benchmark} as its "
                "primary benchmark."
            )
        if not subset["fallback_benchmark"].eq("SPY").all():
            raise UniverseValidationError(
                f"{hypothesis} must use SPY as fallback."
            )

    predecessor = frame["continuity_status"].eq(
        "predecessor_continuity"
    )
    missing_predecessor = predecessor & frame[
        "predecessor_symbols"
    ].eq("")
    if missing_predecessor.any():
        raise UniverseValidationError(
            "predecessor_continuity requires predecessor_symbols: "
            + ", ".join(
                frame.loc[missing_predecessor, "ticker"]
            )
        )

    unexpected_predecessor = (
        ~predecessor
        & frame["predecessor_symbols"].ne("")
    )
    if unexpected_predecessor.any():
        raise UniverseValidationError(
            "predecessor_symbols may only be populated for "
            "predecessor_continuity: "
            + ", ".join(
                frame.loc[unexpected_predecessor, "ticker"]
            )
        )

    target_counts = (
        frame.loc[stock_role, "hypothesis"]
        .value_counts()
        .to_dict()
    )
    minimums = {
        "refining_gasoline": 5,
        "auto_dealers": 5,
        "domestic_leisure_travel": 8,
    }
    for hypothesis, minimum in minimums.items():
        if target_counts.get(hypothesis, 0) < minimum:
            raise UniverseValidationError(
                f"{hypothesis} requires at least {minimum} "
                "constituents."
            )

    for hypothesis in TARGET_HYPOTHESES:
        anchor = frame.loc[
            frame["hypothesis"].eq(hypothesis)
            & frame["analysis_tier"].eq("core")
            & start.eq(STUDY_START_YEAR)
        ]
        if anchor.empty:
            raise UniverseValidationError(
                f"{hypothesis} lacks a core 1998 anchor."
            )


def instrument_is_eligible(
    row: pd.Series,
    event_year: int,
) -> bool:
    flag_column = sample_flag_for_year(event_year)
    start = int(row["analysis_start_year"])
    end_value = row["analysis_end_year"]
    end = (
        FORWARD_YEAR
        if pd.isna(end_value)
        else int(end_value)
    )
    return (
        bool(row[flag_column])
        and start <= event_year <= end
    )


def eligible_instruments(
    universe: pd.DataFrame,
    event_year: int,
    *,
    hypothesis: str | None = None,
    role: str | None = None,
) -> pd.DataFrame:
    sample_for_year(event_year)

    mask = universe.apply(
        instrument_is_eligible,
        axis=1,
        event_year=event_year,
    )
    result = universe.loc[mask].copy()

    if hypothesis is not None:
        if hypothesis not in ALLOWED_HYPOTHESES:
            raise ValueError(
                f"Unknown hypothesis: {hypothesis}"
            )
        result = result.loc[
            result["hypothesis"].eq(hypothesis)
        ]

    if role is not None:
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Unknown role: {role}")
        result = result.loc[result["role"].eq(role)]

    result.sort_values(
        ["hypothesis", "analysis_tier", "ticker"],
        inplace=True,
    )
    result.reset_index(drop=True, inplace=True)
    return result


def resolve_benchmark(
    universe: pd.DataFrame,
    ticker: str,
    event_year: int,
) -> tuple[str, str]:
    matches = universe.loc[universe["ticker"].eq(ticker)]
    if len(matches) != 1:
        raise KeyError(f"Unknown or duplicate ticker: {ticker}")

    row = matches.iloc[0]
    if row["role"] == "market_benchmark":
        return "", "none"

    lookup = universe.set_index("ticker", drop=False)
    for column, resolution in [
        ("primary_benchmark", "primary"),
        ("fallback_benchmark", "fallback"),
    ]:
        candidate = str(row[column]).strip()
        if not candidate:
            continue
        candidate_row = lookup.loc[candidate]
        if instrument_is_eligible(
            candidate_row,
            event_year,
        ):
            return candidate, resolution

    raise UniverseValidationError(
        f"No eligible benchmark for {ticker} in {event_year}."
    )


def build_year_panel(
    universe: pd.DataFrame,
    *,
    start_year: int = STUDY_START_YEAR,
    end_year: int = FORWARD_YEAR,
) -> pd.DataFrame:
    if start_year < STUDY_START_YEAR:
        raise ValueError(
            f"start_year may not precede {STUDY_START_YEAR}."
        )
    if end_year > FORWARD_YEAR:
        raise ValueError(
            f"end_year may not exceed {FORWARD_YEAR}."
        )
    if start_year > end_year:
        raise ValueError(
            "start_year must not exceed end_year."
        )

    rows: list[dict[str, object]] = []
    for event_year in range(start_year, end_year + 1):
        eligible = eligible_instruments(
            universe,
            event_year,
        )

        group_sizes = (
            eligible.loc[
                eligible["role"].eq("hypothesis_stock")
            ]
            .groupby("hypothesis")
            .size()
            .to_dict()
        )

        for item in eligible.itertuples(index=False):
            benchmark, resolution = resolve_benchmark(
                universe,
                item.ticker,
                event_year,
            )

            if item.role == "hypothesis_stock":
                member_count = int(
                    group_sizes[item.hypothesis]
                )
                equal_weight: float | str = (
                    1.0 / member_count
                )
            else:
                member_count = 0
                equal_weight = ""

            rows.append(
                {
                    "event_year": event_year,
                    "sample": sample_for_year(event_year),
                    "ticker": item.ticker,
                    "provider_symbol": item.provider_symbol,
                    "instrument_name": item.instrument_name,
                    "hypothesis": item.hypothesis,
                    "subindustry": item.subindustry,
                    "role": item.role,
                    "analysis_tier": item.analysis_tier,
                    "resolved_benchmark": benchmark,
                    "benchmark_resolution": resolution,
                    "eligible_group_members": member_count,
                    "equal_weight": equal_weight,
                    "continuity_status": item.continuity_status,
                }
            )

    panel = pd.DataFrame(rows, columns=PANEL_COLUMNS)
    panel.sort_values(
        ["event_year", "hypothesis", "role", "ticker"],
        inplace=True,
    )
    panel.reset_index(drop=True, inplace=True)

    if panel.duplicated(["event_year", "ticker"]).any():
        raise UniverseValidationError(
            "Duplicate event_year/ticker rows in universe panel."
        )

    stocks = panel.loc[
        panel["role"].eq("hypothesis_stock")
    ].copy()
    if not stocks.empty:
        weight_sums = stocks.groupby(
            ["event_year", "hypothesis"]
        )["equal_weight"].sum()
        if not weight_sums.map(
            lambda value: abs(float(value) - 1.0) < 1e-12
        ).all():
            raise UniverseValidationError(
                "Equal weights do not sum to one."
            )

    return panel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_csv(
    dataframe: pd.DataFrame,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    dataframe.to_csv(
        temporary,
        index=False,
        encoding="utf-8",
    )
    temporary.replace(path)


def write_manifest(
    *,
    universe_path: Path,
    panel_path: Path,
    manifest_path: Path,
    universe: pd.DataFrame,
    panel: pd.DataFrame,
) -> dict[str, object]:
    hypothesis_counts = (
        universe["hypothesis"]
        .value_counts()
        .sort_index()
        .astype(int)
        .to_dict()
    )
    role_counts = (
        universe["role"]
        .value_counts()
        .sort_index()
        .astype(int)
        .to_dict()
    )
    panel_counts = (
        panel.groupby("event_year")
        .size()
        .astype(int)
        .to_dict()
    )

    payload: dict[str, object] = {
        "artifact": "Labor Day dynamic tradable universe",
        "version": "1.0.0",
        "created_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "study_range": {
            "start_year": STUDY_START_YEAR,
            "discovery_end_year": DISCOVERY_END_YEAR,
            "validation_start_year": (
                VALIDATION_START_YEAR
            ),
            "validation_end_year": VALIDATION_END_YEAR,
            "forward_year": FORWARD_YEAR,
        },
        "universe": {
            "path": str(universe_path.resolve()),
            "sha256": sha256_file(universe_path),
            "rows": len(universe),
            "hypothesis_counts": hypothesis_counts,
            "role_counts": role_counts,
        },
        "year_panel": {
            "path": str(panel_path.resolve()),
            "sha256": sha256_file(panel_path),
            "rows": len(panel),
            "rows_by_year": {
                str(year): count
                for year, count in panel_counts.items()
            },
        },
    }

    manifest_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = manifest_path.with_suffix(
        manifest_path.suffix + ".tmp"
    )
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return payload


def build_universe_artifacts(
    *,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    panel_path: Path = DEFAULT_PANEL_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> UniverseBuildResult:
    universe = read_universe(universe_path)
    panel = build_year_panel(universe)
    atomic_write_csv(panel, panel_path)
    manifest = write_manifest(
        universe_path=universe_path,
        panel_path=panel_path,
        manifest_path=manifest_path,
        universe=universe,
        panel=panel,
    )
    return UniverseBuildResult(
        universe=universe,
        panel=panel,
        manifest=manifest,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the frozen Labor Day universe and build "
            "the year-specific eligibility panel."
        )
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
    )
    parser.add_argument(
        "--panel-output",
        type=Path,
        default=DEFAULT_PANEL_PATH,
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_universe_artifacts(
        universe_path=args.universe,
        panel_path=args.panel_output,
        manifest_path=args.manifest_output,
    )

    counts = (
        result.universe["hypothesis"]
        .value_counts()
        .sort_index()
    )
    print("Labor Day universe validated.")
    print(f"Universe instruments: {len(result.universe)}")
    for hypothesis, count in counts.items():
        print(f"  {hypothesis}: {int(count)}")
    print(
        "Year-specific eligibility rows: "
        f"{len(result.panel)}"
    )
    for year in [
        STUDY_START_YEAR,
        1999,
        2000,
        DISCOVERY_END_YEAR,
        VALIDATION_END_YEAR,
        FORWARD_YEAR,
    ]:
        count = int(
            result.panel["event_year"].eq(year).sum()
        )
        print(f"Eligible instruments in {year}: {count}")
    print(
        "Fallback benchmark rows: "
        f"{int(result.panel['benchmark_resolution'].eq('fallback').sum())}"
    )
    print(
        f"Panel output: {args.panel_output.resolve()}"
    )
    print(
        f"Manifest: {args.manifest_output.resolve()}"
    )


if __name__ == "__main__":
    main()
