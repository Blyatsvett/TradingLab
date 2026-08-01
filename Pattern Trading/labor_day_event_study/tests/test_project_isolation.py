from pathlib import Path


FORBIDDEN_TERMS = {
    "black_friday",
    "thanksgiving_satellite",
    "black_friday_lock",
}

ALLOWED_FILES = {
    Path("RESEARCH_CHARTER.md"),
    Path("config/project.yaml"),
    Path("tests/test_project_isolation.py"),
}


def test_no_black_friday_specific_references() -> None:
    """Prevent accidental import of Black Friday-specific research decisions."""
    project_root = Path(__file__).resolve().parents[1]

    excluded_parts = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "logs",
    }

    text_extensions = {
        ".py",
        ".yaml",
        ".yml",
        ".json",
        ".md",
        ".txt",
        ".toml",
        ".csv",
    }

    violations: list[str] = []

    for path in project_root.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(project_root)

        if relative_path in ALLOWED_FILES:
            continue

        if any(part in excluded_parts for part in path.parts):
            continue

        if path.suffix.lower() not in text_extensions:
            continue

        try:
            content = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue

        for forbidden_term in FORBIDDEN_TERMS:
            if forbidden_term in content:
                violations.append(
                    f"{relative_path}: {forbidden_term}"
                )

    assert not violations, (
        "Black Friday-specific references detected:\n"
        + "\n".join(violations)
    )
