from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .paths import CONFIG_DIR, PROJECT_ROOT


STAGE_REGISTRY_FILE = CONFIG_DIR / "stage_registry.json"


def _load_registry() -> dict[str, Any]:
    with STAGE_REGISTRY_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError(f"Unsupported stage registry: {STAGE_REGISTRY_FILE}")
    for key in ("stage_order", "stage_groups", "ledger_paths", "stages", "output_dirs"):
        if not isinstance(payload.get(key), (list, dict)):
            raise ValueError(f"Stage registry field {key!r} is invalid")
    return payload


_PAYLOAD = _load_registry()
STAGE_ORDER = tuple(str(value) for value in _PAYLOAD["stage_order"])
_GROUPS = _PAYLOAD["stage_groups"]
PERSISTENT_WORKER_STAGES = tuple(_GROUPS["persistent_worker"])
DEADLINE_CRITICAL_STAGES = tuple(_GROUPS["deadline_critical"])
NONCRITICAL_STAGES = tuple(_GROUPS["noncritical"])
DEFERRED_DIAGNOSTICS = tuple(_GROUPS["deferred_diagnostics"])


def _resolve_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Stage registry path must stay inside the project: {value}")
    return (PROJECT_ROOT / path).resolve()


LEDGER_PATHS = MappingProxyType({
    str(key): _resolve_relative(str(value))
    for key, value in _PAYLOAD["ledger_paths"].items()
})

OUTPUT_DIRS = MappingProxyType({
    str(key): _resolve_relative(str(value))
    for key, value in _PAYLOAD["output_dirs"].items()
})

STAGE_REGISTRY = MappingProxyType(_PAYLOAD["stages"])


def resolve_stage_path(stage: str) -> Path:
    """Return the configured ledger path for a stage or diagnostic."""
    try:
        if stage in _PAYLOAD["ledger_paths"]:
            ledger_key = stage
        else:
            ledger_key = STAGE_REGISTRY[stage]["ledger"]
        return LEDGER_PATHS[str(ledger_key)]
    except KeyError as exc:
        raise KeyError(f"Unknown stage or missing ledger mapping: {stage}") from exc


def resolve_stage_output_dir(stage: str) -> Path:
    try:
        return OUTPUT_DIRS[stage]
    except KeyError as exc:
        raise KeyError(f"Unknown stage or missing output mapping: {stage}") from exc


def _validate() -> None:
    known_stages = set(STAGE_REGISTRY)
    if not set(STAGE_ORDER).issubset(known_stages):
        raise ValueError("stage_order contains an unknown stage")
    for group_name in ("persistent_worker", "deadline_critical", "noncritical", "deferred_diagnostics"):
        if not set(_GROUPS[group_name]).issubset(known_stages):
            raise ValueError(f"stage_groups.{group_name} contains an unknown stage")
    for stage, definition in STAGE_REGISTRY.items():
        if str(definition["ledger"]) not in LEDGER_PATHS:
            raise ValueError(f"Stage {stage} refers to an unknown ledger")
    if not set(STAGE_ORDER).issubset(OUTPUT_DIRS):
        raise ValueError("stage_order contains a stage without an output directory")


_validate()
