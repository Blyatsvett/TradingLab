from pathlib import Path

from tools.validate_canonical_pipeline import validate_canonical_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_canonical_pipeline_contract_is_valid() -> None:
    assert validate_canonical_pipeline(PROJECT_ROOT) == []
