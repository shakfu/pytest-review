"""Analyzer for test naming conventions."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig

# Patterns for non-descriptive test names
NON_DESCRIPTIVE_PATTERNS = [
    re.compile(r"^test_?\d+$"),  # test1, test_1, test_2
    re.compile(r"^test_?[a-z]$"),  # test_a, testa
    re.compile(r"^test_?it$", re.IGNORECASE),  # test_it
    re.compile(r"^test_?this$", re.IGNORECASE),  # test_this
    re.compile(r"^test_?foo$", re.IGNORECASE),  # test_foo
    re.compile(r"^test_?bar$", re.IGNORECASE),  # test_bar
    re.compile(r"^test_?example$", re.IGNORECASE),  # test_example
    re.compile(r"^test_?test$", re.IGNORECASE),  # test_test
    re.compile(r"^test_?something$", re.IGNORECASE),  # test_something
]


class NamingAnalyzer(StaticAnalyzer):
    """Analyzes test naming conventions."""

    name = "naming"
    description = "Checks test naming conventions and documentation"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        min_len_opt = self.get_option("min_length", 10)
        self._min_length = int(str(min_len_opt)) if min_len_opt is not None else 10
        self._require_docstring = bool(self.get_option("require_docstring", False))

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        name = test.name

        # Check for non-descriptive names
        for pattern in NON_DESCRIPTIVE_PATTERNS:
            if pattern.match(name):
                result.add_issue(
                    Issue(
                        rule="naming.non_descriptive",
                        message=f"Non-descriptive test name: '{name}'",
                        severity=Severity.WARNING,
                        file_path=test.file_path,
                        line=test.line,
                        test_name=name,
                        suggestion="Use a descriptive name that explains what the test verifies",
                    )
                )
                break

        # Check minimum length (excluding 'test_' prefix)
        name_without_prefix = name[5:] if name.startswith("test_") else name[4:]
        if len(name_without_prefix) < self._min_length:
            result.add_issue(
                Issue(
                    rule="naming.too_short",
                    message=f"Test name too short ({len(name_without_prefix)} chars, "
                    f"minimum {self._min_length})",
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=name,
                    suggestion="Use a more descriptive name that explains the test purpose",
                )
            )

        # Check for docstring
        if self._require_docstring:
            docstring = ast.get_docstring(test.node)
            if not docstring:
                result.add_issue(
                    Issue(
                        rule="naming.missing_docstring",
                        message="Test is missing a docstring",
                        severity=Severity.INFO,
                        file_path=test.file_path,
                        line=test.line,
                        test_name=name,
                        suggestion="Add a docstring explaining what the test verifies",
                    )
                )

        # Check naming convention (should use snake_case)
        if not self._is_snake_case(name):
            result.add_issue(
                Issue(
                    rule="naming.not_snake_case",
                    message=f"Test name '{name}' is not in snake_case",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=name,
                    suggestion="Use snake_case for test names (e.g., test_user_can_login)",
                )
            )

        # Check for unclear abbreviations
        unclear_abbrevs = self._find_unclear_abbreviations(name)
        if unclear_abbrevs:
            result.add_issue(
                Issue(
                    rule="naming.unclear_abbreviation",
                    message=f"Unclear abbreviations: {', '.join(unclear_abbrevs)}",
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=name,
                    suggestion="Use full words instead of abbreviations for clarity",
                )
            )

    @staticmethod
    def _is_snake_case(name: str) -> bool:
        """Check if name follows snake_case convention."""
        # Allow test_ prefix and then snake_case
        return bool(re.match(r"^test_[a-z][a-z0-9_]*$", name))

    @staticmethod
    def _find_unclear_abbreviations(name: str) -> list[str]:
        """Find potentially unclear abbreviations in the name."""
        # Common unclear abbreviations (excluding well-known ones like 'id', 'ok', 'db')
        unclear = []
        parts = name.lower().split("_")
        for part in parts:
            # Skip common/clear abbreviations and very short parts that might be intentional
            if part in ("test", "id", "ok", "db", "api", "url", "io", "ui", "ip", "os"):
                continue
            # Single letter parts (except common ones) or 2-letter uncommon abbreviations
            is_unclear_single = len(part) == 1 and part not in ("a", "i")
            is_unclear_double = (
                len(part) == 2
                and part not in ("is", "in", "on", "to", "or", "an", "as", "at")
                and not part.isdigit()
                and part not in ("no", "if", "do", "my", "up")
            )
            if is_unclear_single or is_unclear_double:
                unclear.append(part)
        return unclear
