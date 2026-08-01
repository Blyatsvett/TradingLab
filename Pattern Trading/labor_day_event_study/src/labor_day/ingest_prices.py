from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .universe import DEFAULT_UNIVERSE_PATH, read_universe


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT / "data" / "raw" / "prices" / "yahoo"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "daily_prices.csv"
)
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests" / "daily_prices_manifest.json"
)

SOURCE_NAME = "Yahoo Finance via yfinance"
SUPPORTED_YFINANCE_VERSION = "1.5.1"
DEFAULT_START_DATE = "1997-01-01"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_REQUEST_DELAY_SECONDS = 0.75

REQUEST_PARAMETERS = {
    "interval": "1d",
    "auto_adjust": False,
    "back_adjust": False,
    "repair": False,
    "actions": True,
    "threads": False,
    "ignore_tz": False,
    "keepna": True,
    "prepost": False,
    "rounding": False,
    "multi_level_index": False,
}

RAW_COLUMNS = [
    "session_datetime",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "dividend",
    "split",
    "capital_gain",
]

NORMALIZED_COLUMNS = [
    "ticker",
    "provider_symbol",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "dividend",
    "split",
    "retrieved_utc",
    "source",
    "source_file",
    "request_hash",
    "raw_sha256",
]

PROVIDER_COLUMN_MAP = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "adj close": "adjusted_close",
    "adjclose": "adjusted_close",
    "adjusted close": "adjusted_close",
    "volume": "volume",
    "dividends": "dividend",
    "dividend": "dividend",
    "stock splits": "split",
    "stock split": "split",
    "splits": "split",
    "capital gains": "capital_gain",
    "capital gain": "capital_gain",
}

REQUIRED_PROVIDER_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
}


class PriceIngestionError(RuntimeError):
    """Raised when price retrieval or normalization cannot complete."""


@dataclass(frozen=True)
class CacheArtifact:
    ticker: str
    provider_symbol: str
    request_hash: str
    raw_path: Path
    metadata_path: Path
    raw_sha256: str
    retrieved_utc: str
    rows: int
    first_session: str
    last_session: str
    cache_status: str


@dataclass(frozen=True)
class PriceIngestionResult:
    prices: pd.DataFrame
    manifest: dict[str, object]
    artifacts: tuple[CacheArtifact, ...]


def default_exclusive_end_date(
    now: datetime | None = None,
) -> str:
    """Return the current New York date, excluding the active session."""
    if now is None:
        current = datetime.now(ZoneInfo("America/New_York"))
    elif now.tzinfo is None:
        current = now.replace(tzinfo=ZoneInfo("America/New_York"))
    else:
        current = now.astimezone(ZoneInfo("America/New_York"))
    return current.date().isoformat()


def validate_date_range(start: str, end: str) -> None:
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(
            "start and end must use YYYY-MM-DD."
        ) from exc

    if start_date >= end_date:
        raise ValueError(
            f"start must precede exclusive end: {start} >= {end}"
        )


def installed_yfinance_version() -> str:
    try:
        return importlib.metadata.version("yfinance")
    except importlib.metadata.PackageNotFoundError as exc:
        raise PriceIngestionError(
            "yfinance is not installed. Install the frozen dependency "
            f"with: python -m pip install yfinance=={SUPPORTED_YFINANCE_VERSION}"
        ) from exc


def validate_yfinance_version(version: str) -> None:
    if version != SUPPORTED_YFINANCE_VERSION:
        raise PriceIngestionError(
            "Phase 1B requires yfinance=="
            f"{SUPPORTED_YFINANCE_VERSION}; found {version}."
        )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def request_payload(
    *,
    ticker: str,
    provider_symbol: str,
    start: str,
    end: str,
    provider_version: str,
) -> dict[str, object]:
    validate_date_range(start, end)
    return {
        "source": SOURCE_NAME,
        "provider_library": "yfinance",
        "provider_version": provider_version,
        "ticker": ticker,
        "provider_symbol": provider_symbol,
        "start": start,
        "end_exclusive": end,
        "parameters": REQUEST_PARAMETERS,
    }


def request_identity(**kwargs: object) -> str:
    return sha256_json(request_payload(**kwargs))[:20]


def safe_filename_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    if not safe:
        raise ValueError("Filename component may not be blank.")
    return safe


def _normalized_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _canonical_column(value: object) -> str:
    if isinstance(value, tuple):
        labels = [
            _normalized_label(part)
            for part in value
            if str(part).strip()
        ]
        for label in labels:
            if label in PROVIDER_COLUMN_MAP:
                return PROVIDER_COLUMN_MAP[label]
        return "__".join(labels)

    label = _normalized_label(value)
    return PROVIDER_COLUMN_MAP.get(
        label,
        re.sub(r"[^a-z0-9]+", "_", label).strip("_"),
    )


def canonicalize_download_frame(
    dataframe: pd.DataFrame | None,
) -> pd.DataFrame:
    """Convert one yfinance response into deterministic raw columns."""
    if dataframe is None or dataframe.empty:
        raise PriceIngestionError(
            "Provider returned no price rows."
        )

    frame = dataframe.copy()
    canonical_columns = [_canonical_column(col) for col in frame.columns]
    if len(canonical_columns) != len(set(canonical_columns)):
        duplicates = sorted(
            {
                name
                for name in canonical_columns
                if canonical_columns.count(name) > 1
            }
        )
        raise PriceIngestionError(
            "Provider response contains duplicate canonical columns: "
            + ", ".join(duplicates)
        )
    frame.columns = canonical_columns

    missing = sorted(REQUIRED_PROVIDER_COLUMNS.difference(frame.columns))
    if missing:
        raise PriceIngestionError(
            "Provider response is missing required columns: "
            + ", ".join(missing)
        )

    index_values = frame.index
    if isinstance(index_values, pd.MultiIndex):
        raise PriceIngestionError(
            "Provider response has a MultiIndex row index."
        )

    session_values = pd.Series(index_values, index=frame.index)
    parsed_sessions: list[str] = []
    for value in session_values:
        try:
            timestamp = pd.Timestamp(value)
        except Exception as exc:
            raise PriceIngestionError(
                f"Could not parse provider session index value {value!r}."
            ) from exc

        if pd.isna(timestamp):
            raise PriceIngestionError(
                "Provider response contains a missing session index."
            )
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("America/New_York")
        parsed_sessions.append(timestamp.isoformat())

    raw = pd.DataFrame({"session_datetime": parsed_sessions})
    for column in [
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
    ]:
        raw[column] = pd.to_numeric(
            frame[column].to_numpy(),
            errors="coerce",
        )

    for column in ["dividend", "split", "capital_gain"]:
        if column in frame.columns:
            raw[column] = pd.Series(
                pd.to_numeric(
                    frame[column].to_numpy(),
                    errors="coerce",
                )
            ).fillna(0.0).to_numpy()
        else:
            raw[column] = 0.0

    if raw["session_datetime"].duplicated().any():
        duplicates = raw.loc[
            raw["session_datetime"].duplicated(keep=False),
            "session_datetime",
        ].tolist()
        raise PriceIngestionError(
            "Provider response contains duplicate sessions: "
            + ", ".join(sorted(set(duplicates)))
        )

    raw.sort_values("session_datetime", inplace=True)
    raw.reset_index(drop=True, inplace=True)
    return raw[RAW_COLUMNS]


def dataframe_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    ).encode("utf-8")


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def immutable_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing != content:
            raise PriceIngestionError(
                f"Refusing to overwrite immutable cache file: {path}"
            )
        return
    path.write_bytes(content)


def _metadata_to_artifact(
    metadata_path: Path,
    metadata: dict[str, object],
    *,
    cache_status: str,
) -> CacheArtifact:
    raw_path = metadata_path.parent / str(metadata["raw_file"])
    if not raw_path.exists():
        raise PriceIngestionError(
            f"Cache metadata references a missing raw file: {raw_path}"
        )

    expected_hash = str(metadata["raw_sha256"])
    actual_hash = sha256_file(raw_path)
    if actual_hash != expected_hash:
        raise PriceIngestionError(
            f"Raw cache hash mismatch for {raw_path}."
        )

    return CacheArtifact(
        ticker=str(metadata["ticker"]),
        provider_symbol=str(metadata["provider_symbol"]),
        request_hash=str(metadata["request_hash"]),
        raw_path=raw_path,
        metadata_path=metadata_path,
        raw_sha256=expected_hash,
        retrieved_utc=str(metadata["retrieved_utc"]),
        rows=int(metadata["rows"]),
        first_session=str(metadata["first_session"]),
        last_session=str(metadata["last_session"]),
        cache_status=cache_status,
    )


def find_cached_artifact(
    *,
    cache_dir: Path,
    ticker: str,
    request_hash: str,
) -> CacheArtifact | None:
    safe_ticker = safe_filename_component(ticker)
    candidates: list[tuple[str, Path, dict[str, object]]] = []
    pattern = f"{safe_ticker}__{request_hash}__*.json"

    for metadata_path in cache_dir.glob(pattern):
        try:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PriceIngestionError(
                f"Could not read cache metadata: {metadata_path}"
            ) from exc

        if str(metadata.get("request_hash", "")) != request_hash:
            continue
        if str(metadata.get("ticker", "")) != ticker:
            continue
        candidates.append(
            (
                str(metadata.get("retrieved_utc", "")),
                metadata_path,
                metadata,
            )
        )

    if not candidates:
        return None

    _, metadata_path, metadata = max(candidates, key=lambda item: item[0])
    return _metadata_to_artifact(
        metadata_path,
        metadata,
        cache_status="reused",
    )


def write_cache_artifact(
    *,
    cache_dir: Path,
    ticker: str,
    provider_symbol: str,
    request_hash: str,
    request: dict[str, object],
    raw: pd.DataFrame,
    retrieved_utc: str,
) -> CacheArtifact:
    raw_bytes = dataframe_csv_bytes(raw)
    raw_hash = sha256_bytes(raw_bytes)
    safe_ticker = safe_filename_component(ticker)
    stem = f"{safe_ticker}__{request_hash}__{raw_hash[:16]}"
    raw_path = cache_dir / f"{stem}.csv"
    metadata_path = cache_dir / f"{stem}.json"

    immutable_write_bytes(raw_path, raw_bytes)

    if metadata_path.exists():
        try:
            existing_metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PriceIngestionError(
                f"Could not read existing cache metadata: {metadata_path}"
            ) from exc
        return _metadata_to_artifact(
            metadata_path,
            existing_metadata,
            cache_status="reused",
        )

    metadata = {
        "schema_version": "1.0.0",
        "ticker": ticker,
        "provider_symbol": provider_symbol,
        "request_hash": request_hash,
        "request": request,
        "retrieved_utc": retrieved_utc,
        "raw_file": raw_path.name,
        "raw_sha256": raw_hash,
        "rows": len(raw),
        "first_session": str(raw["session_datetime"].iloc[0]),
        "last_session": str(raw["session_datetime"].iloc[-1]),
    }
    metadata_bytes = (
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    immutable_write_bytes(metadata_path, metadata_bytes)

    return CacheArtifact(
        ticker=ticker,
        provider_symbol=provider_symbol,
        request_hash=request_hash,
        raw_path=raw_path,
        metadata_path=metadata_path,
        raw_sha256=raw_hash,
        retrieved_utc=retrieved_utc,
        rows=len(raw),
        first_session=str(raw["session_datetime"].iloc[0]),
        last_session=str(raw["session_datetime"].iloc[-1]),
        cache_status="downloaded",
    )


def yfinance_download(
    provider_symbol: str,
    start: str,
    end: str,
    timeout: float,
) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise PriceIngestionError(
            "yfinance could not be imported."
        ) from exc

    result = yf.download(
        tickers=provider_symbol,
        start=start,
        end=end,
        interval=REQUEST_PARAMETERS["interval"],
        auto_adjust=REQUEST_PARAMETERS["auto_adjust"],
        back_adjust=REQUEST_PARAMETERS["back_adjust"],
        repair=REQUEST_PARAMETERS["repair"],
        actions=REQUEST_PARAMETERS["actions"],
        threads=REQUEST_PARAMETERS["threads"],
        ignore_tz=REQUEST_PARAMETERS["ignore_tz"],
        keepna=REQUEST_PARAMETERS["keepna"],
        prepost=REQUEST_PARAMETERS["prepost"],
        rounding=REQUEST_PARAMETERS["rounding"],
        multi_level_index=REQUEST_PARAMETERS[
            "multi_level_index"
        ],
        progress=False,
        timeout=timeout,
    )
    if result is None:
        raise PriceIngestionError(
            f"yfinance returned None for {provider_symbol}."
        )
    return result


def download_with_retries(
    *,
    provider_symbol: str,
    start: str,
    end: str,
    timeout: float,
    max_attempts: int,
    download_func: Callable[[str, str, str, float], pd.DataFrame],
    sleep_func: Callable[[float], None],
) -> pd.DataFrame:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one.")

    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            frame = download_func(
                provider_symbol,
                start,
                end,
                timeout,
            )
            canonicalize_download_frame(frame)
            return frame
        except Exception as exc:
            errors.append(
                f"attempt {attempt}: {type(exc).__name__}: {exc}"
            )
            if attempt < max_attempts:
                sleep_func(float(2 ** (attempt - 1)))

    raise PriceIngestionError(
        f"Failed to download {provider_symbol} after "
        f"{max_attempts} attempt(s): " + " | ".join(errors)
    )


def _session_date(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise PriceIngestionError(
            "Cached raw data contains a missing session timestamp."
        )
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("America/New_York")
    return timestamp.date().isoformat()


def normalized_rows_from_artifact(
    artifact: CacheArtifact,
) -> pd.DataFrame:
    raw = pd.read_csv(
        artifact.raw_path,
        dtype={"session_datetime": str},
    )
    missing = sorted(set(RAW_COLUMNS).difference(raw.columns))
    if missing:
        raise PriceIngestionError(
            f"Cached raw file {artifact.raw_path} is missing: "
            + ", ".join(missing)
        )

    normalized = pd.DataFrame()
    normalized["ticker"] = [artifact.ticker] * len(raw)
    normalized["provider_symbol"] = [
        artifact.provider_symbol
    ] * len(raw)
    normalized["session_date"] = raw["session_datetime"].map(
        _session_date
    )

    for column in [
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "dividend",
        "split",
    ]:
        normalized[column] = pd.to_numeric(
            raw[column],
            errors="coerce",
        )

    normalized["retrieved_utc"] = artifact.retrieved_utc
    normalized["source"] = SOURCE_NAME
    normalized["source_file"] = artifact.raw_path.relative_to(
        PROJECT_ROOT
    ).as_posix() if artifact.raw_path.is_relative_to(PROJECT_ROOT) else str(
        artifact.raw_path.resolve()
    )
    normalized["request_hash"] = artifact.request_hash
    normalized["raw_sha256"] = artifact.raw_sha256

    if normalized["session_date"].duplicated().any():
        raise PriceIngestionError(
            f"Duplicate sessions in cached artifact for {artifact.ticker}."
        )

    return normalized[NORMALIZED_COLUMNS]


def build_normalized_prices(
    artifacts: Iterable[CacheArtifact],
) -> pd.DataFrame:
    frames = [normalized_rows_from_artifact(item) for item in artifacts]
    if not frames:
        raise PriceIngestionError("No cache artifacts were available.")

    prices = pd.concat(frames, ignore_index=True)
    if prices.duplicated(["ticker", "session_date"]).any():
        duplicates = prices.loc[
            prices.duplicated(
                ["ticker", "session_date"],
                keep=False,
            ),
            ["ticker", "session_date"],
        ]
        raise PriceIngestionError(
            "Duplicate ticker/session_date rows after normalization: "
            + duplicates.to_dict(orient="records").__repr__()
        )

    prices.sort_values(
        ["ticker", "session_date"],
        inplace=True,
    )
    prices.reset_index(drop=True, inplace=True)
    return prices[NORMALIZED_COLUMNS]


def _write_prices(prices: pd.DataFrame, path: Path) -> None:
    atomic_write_bytes(path, dataframe_csv_bytes(prices))


def _write_json(payload: object, path: Path) -> None:
    content = (
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, content)


def build_manifest(
    *,
    status: str,
    universe_path: Path,
    output_path: Path,
    provider_version: str,
    start: str,
    end: str,
    artifacts: Iterable[CacheArtifact],
    failures: list[dict[str, str]],
    prices: pd.DataFrame | None,
) -> dict[str, object]:
    artifact_list = list(artifacts)
    raw_artifacts = {
        item.ticker: {
            "provider_symbol": item.provider_symbol,
            "request_hash": item.request_hash,
            "raw_path": str(item.raw_path.resolve()),
            "metadata_path": str(item.metadata_path.resolve()),
            "raw_sha256": item.raw_sha256,
            "retrieved_utc": item.retrieved_utc,
            "rows": item.rows,
            "first_session": item.first_session,
            "last_session": item.last_session,
            "cache_status": item.cache_status,
        }
        for item in sorted(artifact_list, key=lambda value: value.ticker)
    }

    if prices is None:
        output_block: dict[str, object] = {
            "path": str(output_path.resolve()),
            "written": False,
        }
        row_counts: dict[str, int] = {}
    else:
        output_block = {
            "path": str(output_path.resolve()),
            "written": True,
            "sha256": sha256_file(output_path),
            "rows": len(prices),
        }
        row_counts = {
            str(ticker): int(count)
            for ticker, count in prices.groupby("ticker").size().items()
        }

    return {
        "artifact": "Labor Day normalized daily prices",
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source": SOURCE_NAME,
        "provider_library": "yfinance",
        "provider_version": provider_version,
        "supported_provider_version": SUPPORTED_YFINANCE_VERSION,
        "request": {
            "start": start,
            "end_exclusive": end,
            "parameters": REQUEST_PARAMETERS,
        },
        "universe": {
            "path": str(universe_path.resolve()),
            "sha256": sha256_file(universe_path),
        },
        "raw_artifacts": raw_artifacts,
        "output": output_block,
        "row_counts_by_ticker": row_counts,
        "failures": failures,
    }


def ingest_prices(
    *,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    start: str = DEFAULT_START_DATE,
    end: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    request_delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
    refresh: bool = False,
    provider_version: str | None = None,
    universe: pd.DataFrame | None = None,
    download_func: Callable[[str, str, str, float], pd.DataFrame] | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
    now_func: Callable[[], datetime] | None = None,
    log_func: Callable[[str], None] = print,
) -> PriceIngestionResult:
    if end is None:
        current = now_func() if now_func is not None else None
        end = default_exclusive_end_date(current)
    validate_date_range(start, end)

    if timeout <= 0:
        raise ValueError("timeout must be positive.")
    if request_delay < 0:
        raise ValueError("request_delay may not be negative.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one.")

    if provider_version is None:
        provider_version = installed_yfinance_version()
    validate_yfinance_version(provider_version)

    if universe is None:
        universe = read_universe(universe_path)
    else:
        universe = universe.copy()

    required_universe_columns = {"ticker", "provider_symbol"}
    missing_universe = sorted(
        required_universe_columns.difference(universe.columns)
    )
    if missing_universe:
        raise PriceIngestionError(
            "Universe is missing columns: "
            + ", ".join(missing_universe)
        )

    if universe["ticker"].duplicated().any():
        raise PriceIngestionError(
            "Universe contains duplicate canonical tickers."
        )

    download = download_func or yfinance_download
    cache_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[CacheArtifact] = []
    failures: list[dict[str, str]] = []

    ordered = universe.sort_values("ticker").reset_index(drop=True)
    total = len(ordered)

    for index, row in ordered.iterrows():
        ticker = str(row["ticker"])
        provider_symbol = str(row["provider_symbol"])
        request = request_payload(
            ticker=ticker,
            provider_symbol=provider_symbol,
            start=start,
            end=end,
            provider_version=provider_version,
        )
        identity = sha256_json(request)[:20]

        cached = None if refresh else find_cached_artifact(
            cache_dir=cache_dir,
            ticker=ticker,
            request_hash=identity,
        )

        if cached is not None:
            artifacts.append(cached)
            log_func(
                f"[{index + 1}/{total}] {ticker}: reused cache "
                f"({cached.rows} rows)"
            )
            continue

        log_func(
            f"[{index + 1}/{total}] {ticker}: downloading "
            f"{start} to {end} (exclusive)"
        )
        try:
            downloaded = download_with_retries(
                provider_symbol=provider_symbol,
                start=start,
                end=end,
                timeout=timeout,
                max_attempts=max_attempts,
                download_func=download,
                sleep_func=sleep_func,
            )
            raw = canonicalize_download_frame(downloaded)
            retrieved_utc = datetime.now(timezone.utc).isoformat()
            artifact = write_cache_artifact(
                cache_dir=cache_dir,
                ticker=ticker,
                provider_symbol=provider_symbol,
                request_hash=identity,
                request=request,
                raw=raw,
                retrieved_utc=retrieved_utc,
            )
            artifacts.append(artifact)
            log_func(
                f"[{index + 1}/{total}] {ticker}: cached "
                f"{artifact.rows} rows"
            )
        except Exception as exc:
            failures.append(
                {
                    "ticker": ticker,
                    "provider_symbol": provider_symbol,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            log_func(
                f"[{index + 1}/{total}] {ticker}: FAILED - {exc}"
            )

        if index + 1 < total and request_delay:
            sleep_func(request_delay)

    if failures:
        manifest = build_manifest(
            status="FAIL",
            universe_path=universe_path,
            output_path=output_path,
            provider_version=provider_version,
            start=start,
            end=end,
            artifacts=artifacts,
            failures=failures,
            prices=None,
        )
        _write_json(manifest, manifest_path)
        raise PriceIngestionError(
            f"Price ingestion failed for {len(failures)} ticker(s). "
            f"Successful caches were retained. Inspect {manifest_path}."
        )

    prices = build_normalized_prices(artifacts)
    _write_prices(prices, output_path)

    manifest = build_manifest(
        status="PASS",
        universe_path=universe_path,
        output_path=output_path,
        provider_version=provider_version,
        start=start,
        end=end,
        artifacts=artifacts,
        failures=[],
        prices=prices,
    )
    _write_json(manifest, manifest_path)

    return PriceIngestionResult(
        prices=prices,
        manifest=manifest,
        artifacts=tuple(artifacts),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download and cache the Phase 1 Labor Day daily-price "
            "universe."
        )
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )
    parser.add_argument(
        "--start",
        default=DEFAULT_START_DATE,
    )
    parser.add_argument(
        "--end",
        default=None,
        help=(
            "Exclusive YYYY-MM-DD end date. Defaults to the current "
            "New York date, thereby excluding the active session."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Download again even when an immutable cache artifact "
            "already satisfies the request."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = ingest_prices(
        universe_path=args.universe,
        cache_dir=args.cache_dir,
        output_path=args.output,
        manifest_path=args.manifest_output,
        start=args.start,
        end=args.end,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        request_delay=args.request_delay,
        refresh=args.refresh,
    )

    downloaded = sum(
        item.cache_status == "downloaded"
        for item in result.artifacts
    )
    reused = sum(
        item.cache_status == "reused"
        for item in result.artifacts
    )
    print("Daily-price ingestion completed.")
    print(f"Status: {result.manifest['status']}")
    print(f"Provider version: {result.manifest['provider_version']}")
    print(f"Tickers: {len(result.artifacts)}")
    print(f"Downloaded artifacts: {downloaded}")
    print(f"Reused artifacts: {reused}")
    print(f"Normalized rows: {len(result.prices)}")
    print(
        "Date span: "
        f"{result.prices['session_date'].min()} to "
        f"{result.prices['session_date'].max()}"
    )
    print(f"Output: {args.output.resolve()}")
    print(f"Manifest: {args.manifest_output.resolve()}")


if __name__ == "__main__":
    main()
