"""Check the Python packages required by the Regime Trading project."""

from __future__ import annotations

import importlib
import sys


REQUIRED_MODULES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "openpyxl": "openpyxl",
    "pytest": "pytest",
    "yfinance": "yfinance",
}


def main() -> int:
    missing: list[str] = []
    versions: list[str] = []
    for label, module_name in REQUIRED_MODULES.items():
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            missing.append(label)
            continue
        version = getattr(module, "__version__", "available")
        versions.append(f"{label}={version}")

    if missing:
        print("Missing Regime Trading dependencies: " + ", ".join(missing))
        print(
            "Run .\\setup_regime_trading.ps1 with the project .venv, "
            "not the Codex-bundled Python runtime."
        )
        return 1

    print("Regime Trading dependencies: " + ", ".join(versions))
    print(f"Python: {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
