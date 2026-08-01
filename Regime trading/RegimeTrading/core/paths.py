from __future__ import annotations

import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
PATHS_CONFIG_FILE = CONFIG_DIR / "paths.json"


def _load_path_config() -> dict[str, object]:
    if not PATHS_CONFIG_FILE.exists():
        return {}
    with PATHS_CONFIG_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Path configuration must be a JSON object: {PATHS_CONFIG_FILE}")
    return payload


_PATH_CONFIG = _load_path_config()


def _resolve_path(key: str, default: str) -> Path:
    configured = os.environ.get(f"REGIME_TRADING_{key.upper()}")
    if configured is None:
        configured = _PATH_CONFIG.get(key, default)
    path = Path(str(configured)).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


DATA_DIR = _resolve_path("data_dir", "data")
MARKET_SOURCE_DIR = _resolve_path("market_source_dir", "data/source/market")
REFERENCE_DATA_DIR = _resolve_path("reference_data_dir", "data/source/reference")
RECONCILIATION_DATA_DIR = _resolve_path(
    "reconciliation_data_dir", "data/source/reference/reconciliation"
)
LOG_DIR = _resolve_path("log_dir", "logs")
SNAPSHOT_DIR = _resolve_path(
    "snapshot_dir",
    "data/step9_morning_v2_snapshots",
)
SESSION_REGISTRY_DIR = _resolve_path(
    "session_registry_dir",
    "data/prospective_session_registry",
)
KPI_OUTPUT_DIR = _resolve_path("kpi_output_dir", "data/step9kpi")
POWERBI_DIR = _resolve_path("powerbi_dir", "data/powerbi")
VALIDATION_OUTPUT_DIR = _resolve_path(
    "validation_output_dir",
    "data/v2_validation",
)
NASDAQ_RAW_DIR = _resolve_path("nasdaq_raw_dir", "data/nasdaq_raw")
COLLECTOR_OUTPUT_DIR = _resolve_path("nasdaq_output_dir", "data/outputs/collector/nasdaq")
FREEZE_DIRS = {
    str(key): _resolve_path(f"freeze_{key}", str(value))
    for key, value in dict(_PATH_CONFIG.get("freeze_dirs", {})).items()
}
LEGACY_OUTPUT_DIRS = {
    str(key): _resolve_path(f"legacy_output_{key}", str(value))
    for key, value in dict(_PATH_CONFIG.get("legacy_output_dirs", {})).items()
}
SHADOW_OUTPUT_DIRS = {
    str(key): _resolve_path(f"shadow_output_{key}", str(value))
    for key, value in dict(_PATH_CONFIG.get("shadow_output_dirs", {})).items()
}


def shadow_output_path(filename: str) -> Path:
    """Resolve active Step 9I/9L shadow output files by family."""
    if filename.startswith("step9i_v2_"):
        family = "step9i_v2"
    elif filename.startswith("step9l_v3_"):
        family = "step9l_v3"
    else:
        raise ValueError(f"Unsupported active shadow output filename: {filename}")
    return SHADOW_OUTPUT_DIRS[family] / filename


def legacy_output_path(filename: str) -> Path:
    """Resolve a legacy research output through the configured family directory."""
    if filename == "regime_holdout_universe_registry.csv":
        return REFERENCE_DATA_DIR / filename
    if filename.startswith("v1_validation_"):
        family = "v1_validation"
    elif filename.startswith("step9ir_v2_"):
        family = "step9ir_v2"
    elif filename.startswith("step9ir_"):
        family = "step9ir_v1"
    elif filename.startswith("step9j_v2_"):
        family = "step9j_v2"
    elif filename.startswith("step9j_"):
        family = "step9j"
    elif filename.startswith("step9k_"):
        family = "step9k"
    elif filename.startswith("step9m_"):
        family = "step9m"
    elif filename.startswith("step9n_"):
        family = "step9n"
    elif filename.startswith("step9o_"):
        family = "step9o"
    elif filename.startswith("regime_gap_recovery_"):
        family = "gap_recovery"
    elif filename.startswith("regime_v1_timing_") or filename.startswith("regime_v1_timing_comparison_"):
        family = "v1_timing"
    elif filename.startswith("regime_feature_") or filename in {"regime_daily_features.csv", "regime_point_in_time_audit.csv"}:
        family = "regime_features"
    elif filename.startswith("regime_taxonomy_") or filename == "regime_daily_taxonomy.csv":
        family = "regime_taxonomy"
    elif filename.startswith("regime_playbook_"):
        family = "regime_playbook"
    elif filename.startswith("regime_challenger_"):
        family = "regime_challenger"
    elif filename.startswith("instrument_taxonomy_"):
        family = "instrument_taxonomy"
    elif filename.startswith("regime_sector_strategy_"):
        family = "regime_sector_strategy"
    elif filename.startswith("regime_state_filtered_"):
        family = "regime_state_filtered"
    elif filename.startswith("regime_holdout_"):
        family = "regime_holdout"
    else:
        return DATA_DIR / filename
    return LEGACY_OUTPUT_DIRS[family] / filename

DATA_DIR.mkdir(parents=True, exist_ok=True)
MARKET_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_DATA_DIR.mkdir(parents=True, exist_ok=True)
RECONCILIATION_DATA_DIR.mkdir(parents=True, exist_ok=True)
COLLECTOR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

INTRADAY_DB = MARKET_SOURCE_DIR / "intraday_prices.db"
POWERBI_WORKBOOK = KPI_OUTPUT_DIR / "powerbi_exports.xlsx"

# The original project is treated as a read-only market-data source.
# The default is relative to this repository so the project works on another
# Windows machine or inside an isolated mock clone. Both environment variable
# names are supported for backward compatibility.
source_override = os.environ.get("REGIME_TRADING_SOURCE_INTRADAY_DB")
if source_override is None:
    source_override = os.environ.get("REGIME_TRADING_SOURCE_DB")
if source_override is not None:
    source_path = Path(source_override).expanduser()
    SOURCE_INTRADAY_DB = (
        source_path if source_path.is_absolute() else (PROJECT_ROOT / source_path).resolve()
    )
else:
    SOURCE_INTRADAY_DB = _resolve_path(
        "source_intraday_db",
        "../Intraday/data/intraday_prices.db",
    )
