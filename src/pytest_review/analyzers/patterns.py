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
        self._with_context_calls: set[int] = set()  # ids of Call nodes in with-items

    def visit_With(self, node: ast.With) -> None:
        # Record Call nodes that appear as context expressions in with-items
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                self._with_context_calls.add(id(item.context_expr))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # Check for hardcoded absolute paths passed to path-consuming calls
        if self._is_path_consuming(func):
            for arg in node.args:
                self._check_hardcoded_path_arg(arg)
            for kw in node.keywords:
                if kw.arg in ("path", "name", "src", "dst", "target", "file"):
                    self._check_hardcoded_path_arg(kw.value)

        # Check for time.sleep()
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "sleep"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        ):
            self.issues.append(
                (
                    node.lineno,
                    "patterns.sleep_in_test",
                    "time.sleep() in test makes it slow and potentially flaky",
                    Severity.WARNING,
                    "Use mocking or async patterns instead of sleeping",
                )
            )

        # Check for subprocess.run() without check=True
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            has_check = any(isinstance(kw.arg, str) and kw.arg == "check" for kw in node.keywords)
            if not has_check:
                self.issues.append(
                    (
                        node.lineno,
                        "patterns.subprocess_no_check",
                        "subprocess.run() without check=True silently ignores failures",
                        Severity.WARNING,
                        "Add check=True to raise on non-zero exit codes",
                    )
                )

        # Check for os.system() or subprocess without proper handling
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
            and func.attr == "system"
        ):
            self.issues.append(
                (
                    node.lineno,
                    "patterns.os_system",
                    "os.system() is deprecated, use subprocess module",
                    Severity.INFO,
                    "Use subprocess.run() for better control and security",
                )
            )

        # Check for network/IO calls that may be slow without mocking
        self._check_slow_call(node)

        self.generic_visit(node)

    # module.method patterns that indicate potentially slow operations
    _SLOW_CALLS: dict[str, set[str]] = {
        "requests": {"get", "post", "put", "patch", "delete", "head", "options", "request"},
        "httpx": {"get", "post", "put", "patch", "delete", "head", "options", "request"},
        "urllib": {"urlopen"},
    }

    def _check_slow_call(self, node: ast.Call) -> None:
        """Detect network calls and DB operations that may be slow."""
        func = node.func
        # module.method() -- requests.get(), httpx.post(), etc.
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = func.value.id
            method = func.attr
            if module in self._SLOW_CALLS and (
                not self._SLOW_CALLS[module] or method in self._SLOW_CALLS[module]
            ):
                self.issues.append(
                    (
                        node.lineno,
                        "patterns.slow_call",
                        f"{module}.{method}() performs network I/O without mocking",
                        Severity.WARNING,
                        "Mock network calls or use a fixture to avoid slow/flaky tests",
                    )
                )
                return
        # urllib.request.urlopen()
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "urlopen"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "request"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "urllib"
        ):
            self.issues.append(
                (
                    node.lineno,
                    "patterns.slow_call",
                    "urllib.request.urlopen() performs network I/O",
                    Severity.WARNING,
                    "Mock network calls or use a fixture to avoid slow/flaky tests",
                )
            )
            return
        # cursor.execute() / session.query() -- common DB patterns
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("execute", "query")
            and isinstance(func.value, ast.Name)
            and func.value.id in ("cursor", "session", "conn", "connection", "db")
        ):
            self.issues.append(
                (
                    node.lineno,
                    "patterns.slow_call",
                    f"{func.value.id}.{func.attr}() may perform database I/O",
                    # Kept at INFO: this matches on variable *names*, not a known
                    # API, so it is a guess in a way the network checks are not.
                    Severity.INFO,
                    "Use a test database fixture or mock DB calls",
                )
            )

    # modules whose methods take filesystem paths
    _PATH_MODULES = frozenset({"os", "shutil", "glob", "tempfile"})

    def _is_path_consuming(self, func: ast.expr) -> bool:
        """True when *func* is a call target that consumes filesystem paths."""
        if isinstance(func, ast.Name):
            return func.id in ("open", "Path")
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                return func.value.id in self._PATH_MODULES
            # os.path.join / os.path.abspath / ...
            if (
                isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
                and func.value.attr == "path"
            ):
                return True
        return False

    @staticmethod
    def _looks_like_absolute_path(value: str) -> bool:
        """True for strings that look like an absolute filesystem path."""
        if value.startswith("/") and len(value) > 5 and "/" in value[1:]:
            return any(p in value.lower() for p in ["/home/", "/users/", "/tmp/", "/var/", "/etc/"])
        # Windows paths:  C:\...  or  C:/...
        return len(value) > 3 and value[1] == ":" and value[2] in ("\\", "/")

    def _check_hardcoded_path_arg(self, arg: ast.expr) -> None:
        """Flag a string constant argument that is an absolute path."""
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            return
        value = arg.value
        if not self._looks_like_absolute_path(value):
            return
        display = f"{value[:50]}..." if len(value) > 50 else value
        self.issues.append(
            (
                arg.lineno,
                "patterns.hardcoded_path",
                f"Hardcoded absolute path: '{display}'",
                Severity.INFO,
                "Use tmp_path fixture or pathlib for cross-platform paths",
            )
        )

    def visit_Assign(self, node: ast.Assign) -> None:
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
