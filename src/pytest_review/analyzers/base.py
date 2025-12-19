"""Base analyzer interface for pytest-review."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


class Severity(Enum):
    """Severity levels for issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        order = [Severity.INFO, Severity.WARNING, Severity.ERROR]
        return order.index(self) < order.index(other)


@dataclass
class Issue:
    """A quality issue found by an analyzer."""

    rule: str
    message: str
    severity: Severity
    file_path: Path | None = None
    line: int | None = None
    test_name: str | None = None
    suggestion: str | None = None

    def __str__(self) -> str:
        location = ""
        if self.file_path:
            location = f"{self.file_path}"
            if self.line:
                location += f":{self.line}"
            location += " "
        test = f"[{self.test_name}] " if self.test_name else ""
        return f"{location}{test}{self.message}"


@dataclass
class AnalyzerResult:
    """Result from running an analyzer."""

    analyzer_name: str
    issues: list[Issue] = field(default_factory=list)
    score: float = 100.0
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        """Check if result contains any errors."""
        return any(issue.severity == Severity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if result contains any warnings."""
        return any(issue.severity == Severity.WARNING for issue in self.issues)

    @property
    def issue_count(self) -> int:
        """Total number of issues."""
        return len(self.issues)

    def add_issue(self, issue: Issue) -> None:
        """Add an issue to the result."""
        self.issues.append(issue)


@dataclass
class TestItemInfo:
    """Information about a test function for analysis."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    name: str
    file_path: Path
    line: int
    node: ast.FunctionDef | ast.AsyncFunctionDef
    source: str
    class_name: str | None = None

    @property
    def full_name(self) -> str:
        """Full qualified name of the test."""
        if self.class_name:
            return f"{self.class_name}::{self.name}"
        return self.name


class Analyzer(ABC):
    """Base class for test quality analyzers."""

    name: str = "base"
    description: str = "Base analyzer"

    def __init__(self, config: ReviewConfig) -> None:
        self.config = config
        self._analyzer_config = config.get_analyzer_config(self.name)

    @property
    def enabled(self) -> bool:
        """Check if this analyzer is enabled."""
        return self._analyzer_config.enabled

    def get_option(self, name: str, default: object = None) -> object:
        """Get a configuration option for this analyzer."""
        return self._analyzer_config.options.get(name, default)

    @abstractmethod
    def analyze(self, test: TestItemInfo) -> AnalyzerResult:
        """Analyze a single test and return results."""
        ...

    def analyze_all(self, tests: list[TestItemInfo]) -> list[AnalyzerResult]:
        """Analyze multiple tests."""
        return [self.analyze(test) for test in tests]


class StaticAnalyzer(Analyzer):
    """Base class for static (AST-based) analyzers."""

    def analyze(self, test: TestItemInfo) -> AnalyzerResult:
        """Analyze a test using AST."""
        result = AnalyzerResult(analyzer_name=self.name)
        self._analyze_ast(test, result)
        return result

    @abstractmethod
    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        """Perform AST-based analysis. Subclasses implement this."""
        ...


class DynamicAnalyzer(Analyzer):
    """Base class for dynamic (runtime) analyzers."""

    def analyze(self, test: TestItemInfo) -> AnalyzerResult:
        """Dynamic analyzers need runtime data, so base analyze returns empty result."""
        return AnalyzerResult(analyzer_name=self.name)

    @abstractmethod
    def on_test_start(self, test_name: str) -> None:
        """Called when a test starts executing."""
        ...

    @abstractmethod
    def on_test_end(self, test_name: str, passed: bool, duration: float) -> None:
        """Called when a test finishes executing."""
        ...

    @abstractmethod
    def get_results(self) -> list[AnalyzerResult]:
        """Get accumulated results after test run."""
        ...
