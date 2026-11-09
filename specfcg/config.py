"""Configuration dataclasses and YAML loading."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    model: str = "gpt-4.1"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    temperature: float = 0.0
    cache_dir: str = ".cache/llm"


@dataclass
class DeviceConfig:
    serial: str | None = None
    timeout_s: int = 30


@dataclass
class PathConfig:
    root: str = "."
    cards: str = "cards"
    graph: str = "graph"
    traces: str = "traces"
    runs: str = "runs"
    state: str = "state"
    completion: str = "completion"


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    paths: PathConfig = field(default_factory=PathConfig)


def _build(cls: type, data: dict[str, Any] | None) -> Any:
    """Build a dataclass from a mapping, keeping defaults for absent keys."""
    data = data or {}
    known = {f.name for f in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in known})


def load_config(path: Path) -> AppConfig:
    """Load an AppConfig from YAML, merging it over the dataclass defaults."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return AppConfig(
        llm=_build(LLMConfig, raw.get("llm")),
        device=_build(DeviceConfig, raw.get("device")),
        paths=_build(PathConfig, raw.get("paths")),
    )
