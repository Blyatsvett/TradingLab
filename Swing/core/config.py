"""Configuration objects for the canonical Swing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "canonical_strategy.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "prices.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "canonical"


@dataclass(frozen=True)
class StrategyConfig:
    strategy_name: str = "swedish_momentum_next_open_v1"
    initial_capital: float = 10_000.0
    momentum_window: int = 5
    regime_window: int = 20
    bull_threshold: float = 0.03
    bear_threshold: float = -0.03
    exclude_bear_regime: bool = True
    top_n: int = 2
    rebalance_every_sessions: int = 3
    trading_cost_bps_per_side: float = 5.0
    start_date: str | None = None
    end_date: str | None = None

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.momentum_window < 1 or self.regime_window < 1:
            raise ValueError("feature windows must be positive")
        if self.top_n < 1:
            raise ValueError("top_n must be at least 1")
        if self.rebalance_every_sessions < 1:
            raise ValueError("rebalance_every_sessions must be at least 1")
        if self.trading_cost_bps_per_side < 0:
            raise ValueError("trading_cost_bps_per_side cannot be negative")
        if self.bear_threshold >= self.bull_threshold:
            raise ValueError("bear_threshold must be below bull_threshold")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    config = StrategyConfig(**payload)
    config.validate()
    return config
