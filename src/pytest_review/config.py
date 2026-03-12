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
class AssertionsConfig:
    """Typed configuration for the assertions analyzer."""

    enabled: bool = True
    min_assertions: int = 1


@dataclass
class NamingConfig:
    """Typed configuration for the naming analyzer."""

    enabled: bool = True
    min_length: int = 10
    require_docstring: bool = False


@dataclass
class ComplexityConfig:
    """Typed configuration for the complexity analyzer."""

    enabled: bool = True
    max_statements: int = 20
    max_depth: int = 3
    max_complexity: int = 5


@dataclass
class PatternsConfig:
    """Typed configuration for the patterns analyzer."""

    enabled: bool = True


@dataclass
class IsolationConfig:
    """Typed configuration for the isolation analyzer."""

    enabled: bool = True


@dataclass
class PerformanceConfig:
    """Typed configuration for the performance analyzer."""

    enabled: bool = True
    slow_threshold_ms: float = 500.0
    very_slow_threshold_ms: float = 2000.0


@dataclass
class SmellsConfig:
    """Typed configuration for the smells analyzer."""

    enabled: bool = True
    max_assertions_without_message: int = 1
    check_magic_numbers: bool = True
    check_eager_test: bool = True


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
                enabled = analyzer_data.get("enabled", True)
                options = {k: v for k, v in analyzer_data.items() if k != "enabled"}
                analyzers[name] = AnalyzerConfig(enabled=enabled, options=options)
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

    def get_assertions_config(self) -> AssertionsConfig:
        """Get typed configuration for the assertions analyzer."""
        raw = self.get_analyzer_config("assertions")
        return AssertionsConfig(
            enabled=raw.enabled,
            min_assertions=int(raw.options.get("min_assertions", 1)),
        )

    def get_naming_config(self) -> NamingConfig:
        """Get typed configuration for the naming analyzer."""
        raw = self.get_analyzer_config("naming")
        return NamingConfig(
            enabled=raw.enabled,
            min_length=int(raw.options.get("min_length", 10)),
            require_docstring=bool(raw.options.get("require_docstring", False)),
        )

    def get_complexity_config(self) -> ComplexityConfig:
        """Get typed configuration for the complexity analyzer."""
        raw = self.get_analyzer_config("complexity")
        return ComplexityConfig(
            enabled=raw.enabled,
            max_statements=int(raw.options.get("max_statements", 20)),
            max_depth=int(raw.options.get("max_depth", 3)),
            max_complexity=int(raw.options.get("max_complexity", 5)),
        )

    def get_patterns_config(self) -> PatternsConfig:
        """Get typed configuration for the patterns analyzer."""
        raw = self.get_analyzer_config("patterns")
        return PatternsConfig(enabled=raw.enabled)

    def get_isolation_config(self) -> IsolationConfig:
        """Get typed configuration for the isolation analyzer."""
        raw = self.get_analyzer_config("isolation")
        return IsolationConfig(enabled=raw.enabled)

    def get_performance_config(self) -> PerformanceConfig:
        """Get typed configuration for the performance analyzer."""
        raw = self.get_analyzer_config("performance")
        return PerformanceConfig(
            enabled=raw.enabled,
            slow_threshold_ms=float(raw.options.get("slow_threshold_ms", 500.0)),
            very_slow_threshold_ms=float(raw.options.get("very_slow_threshold_ms", 2000.0)),
        )

    def get_smells_config(self) -> SmellsConfig:
        """Get typed configuration for the smells analyzer."""
        raw = self.get_analyzer_config("smells")
        return SmellsConfig(
            enabled=raw.enabled,
            max_assertions_without_message=int(
                raw.options.get("max_assertions_without_message", 1)
            ),
            check_magic_numbers=bool(raw.options.get("check_magic_numbers", True)),
            check_eager_test=bool(raw.options.get("check_eager_test", True)),
        )
