"""Analyzer for anti-patterns in tests."""

from __future__ import annotations

import ast
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


class PatternVisitor(ast.NodeVisitor):
    """AST visitor that detects anti-patterns."""

    def __init__(self) -> None:
        self.issues: list[tuple[int, str, str, Severity, str | None]] = []
        # (line, rule, message, severity, suggestion)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # Check for bare except
        if node.type is None:
            self.issues.append((
                node.lineno,
                "patterns.bare_except",
                "Bare 'except:' clause catches all exceptions including KeyboardInterrupt",
                Severity.WARNING,
                "Specify the exception type, e.g., 'except Exception:'",
            ))
        # Check for except Exception with pass
        if node.type and isinstance(node.type, ast.Name) and node.type.id == "Exception":
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                self.issues.append((
                    node.lineno,
                    "patterns.swallowed_exception",
                    "Exception is caught and silently ignored",
                    Severity.WARNING,
                    "Log the exception or re-raise if appropriate",
                ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # Check for time.sleep()
        if isinstance(func, ast.Attribute) and func.attr == "sleep":
            if isinstance(func.value, ast.Name) and func.value.id == "time":
                self.issues.append((
                    node.lineno,
                    "patterns.sleep_in_test",
                    "time.sleep() in test makes it slow and potentially flaky",
                    Severity.WARNING,
                    "Use mocking or async patterns instead of sleeping",
                ))

        # Check for print() statements
        if isinstance(func, ast.Name) and func.id == "print":
            self.issues.append((
                node.lineno,
                "patterns.print_statement",
                "print() statement in test - use logging or assertions instead",
                Severity.INFO,
                "Remove print or use proper logging/capfd fixture",
            ))

        # Check for open() without context manager (basic check)
        if isinstance(func, ast.Name) and func.id == "open":
            # This is in a Call context, check if parent is With
            self.issues.append((
                node.lineno,
                "patterns.open_without_context",
                "open() should be used with a context manager (with statement)",
                Severity.INFO,
                "Use 'with open(...) as f:' to ensure file is properly closed",
            ))

        # Check for os.system() or subprocess without proper handling
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                if func.value.id == "os" and func.attr == "system":
                    self.issues.append((
                        node.lineno,
                        "patterns.os_system",
                        "os.system() is deprecated, use subprocess module",
                        Severity.INFO,
                        "Use subprocess.run() for better control and security",
                    ))

        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # Check for hardcoded paths (basic heuristic)
        if isinstance(node.value, str):
            value = node.value
            # Check for absolute paths
            if value.startswith("/") and len(value) > 5 and "/" in value[1:]:
                # Looks like an absolute path
                if any(
                    p in value.lower()
                    for p in ["/home/", "/users/", "/tmp/", "/var/", "/etc/"]
                ):
                    self.issues.append((
                        node.lineno,
                        "patterns.hardcoded_path",
                        f"Hardcoded absolute path: '{value[:50]}...' if len(value) > 50 else '{value}'",
                        Severity.WARNING,
                        "Use tmp_path fixture or pathlib for cross-platform paths",
                    ))
            # Windows paths
            elif len(value) > 3 and value[1:3] == ":\\":
                self.issues.append((
                    node.lineno,
                    "patterns.hardcoded_path",
                    f"Hardcoded Windows path detected",
                    Severity.WARNING,
                    "Use tmp_path fixture or pathlib for cross-platform paths",
                ))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "mock":
                self.issues.append((
                    node.lineno,
                    "patterns.legacy_mock",
                    "Using 'import mock' - prefer unittest.mock (built-in since Python 3.3)",
                    Severity.INFO,
                    "Use 'from unittest.mock import Mock, patch' instead",
                ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "mock":
            self.issues.append((
                node.lineno,
                "patterns.legacy_mock",
                "Using 'from mock import' - prefer unittest.mock",
                Severity.INFO,
                "Use 'from unittest.mock import ...' instead",
            ))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Check for mutable default-like patterns at module/class level
        # This is a simplified check
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        # Check for 'is' comparison with literals
        for i, op in enumerate(node.ops):
            if isinstance(op, (ast.Is, ast.IsNot)):
                comparator = node.comparators[i] if i < len(node.comparators) else None
                left = node.left if i == 0 else node.comparators[i - 1]

                for operand in [left, comparator]:
                    if isinstance(operand, ast.Constant):
                        if isinstance(operand.value, (int, str, float)) and operand.value not in (
                            True,
                            False,
                            None,
                        ):
                            self.issues.append((
                                node.lineno,
                                "patterns.is_literal",
                                f"Using 'is' with literal value - use '==' instead",
                                Severity.WARNING,
                                "'is' compares identity, not equality; use '==' for value comparison",
                            ))
                            break
        self.generic_visit(node)


class PatternsAnalyzer(StaticAnalyzer):
    """Analyzes tests for anti-patterns."""

    name = "patterns"
    description = "Detects common anti-patterns in tests"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        visitor = PatternVisitor()
        visitor.visit(test.node)

        for line, rule, message, severity, suggestion in visitor.issues:
            result.add_issue(
                Issue(
                    rule=rule,
                    message=message,
                    severity=severity,
                    file_path=test.file_path,
                    line=line,
                    test_name=test.name,
                    suggestion=suggestion,
                )
            )

        # Store metadata
        result.metadata["pattern_issues"] = len(visitor.issues)
