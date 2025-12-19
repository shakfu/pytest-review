"""Configuration handling for pytest-review."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]


@dataclass
class AnalyzerConfig:
    """Configuration for an individual analyzer."""

    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewConfig:
    """Main configuration for pytest-review."""

    enabled: bool = True
    strict: bool = False
    min_score: int = 0
    analyzers: dict[str, AnalyzerConfig] = field(default_factory=dict)
    ignore_paths: list[str] = field(default_factory=list)
    ignore_rules: list[str] = field(default_factory=list)

    @classmethod
    def from_pyproject(cls, path: Path | None = None) -> ReviewConfig:
        """Load configuration from pyproject.toml."""
        if path is None:
            path = Path.cwd() / "pyproject.toml"

        if not path.exists():
            return cls()

        with open(path, "rb") as f:
            data = tomllib.load(f)

        tool_config = data.get("tool", {}).get("pytest-review", {})
        return cls.from_dict(tool_config)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewConfig:
        """Create configuration from a dictionary."""
        analyzers: dict[str, AnalyzerConfig] = {}
        analyzers_data = data.get("analyzers", {})

        for name, analyzer_data in analyzers_data.items():
            if isinstance(analyzer_data, dict):
                enabled = analyzer_data.pop("enabled", True)
                analyzers[name] = AnalyzerConfig(enabled=enabled, options=analyzer_data)
            else:
                analyzers[name] = AnalyzerConfig(enabled=bool(analyzer_data))

        ignore_config = data.get("ignore", {})

        return cls(
            enabled=data.get("enabled", True),
            strict=data.get("strict", False),
            min_score=data.get("min_score", 0),
            analyzers=analyzers,
            ignore_paths=ignore_config.get("paths", []),
            ignore_rules=ignore_config.get("rules", []),
        )

    def get_analyzer_config(self, name: str) -> AnalyzerConfig:
        """Get configuration for a specific analyzer."""
        return self.analyzers.get(name, AnalyzerConfig())

    def is_analyzer_enabled(self, name: str) -> bool:
        """Check if an analyzer is enabled."""
        config = self.get_analyzer_config(name)
        return config.enabled

    def get_analyzer_option(self, analyzer: str, option: str, default: Any = None) -> Any:
        """Get a specific option for an analyzer."""
        config = self.get_analyzer_config(analyzer)
        return config.options.get(option, default)
