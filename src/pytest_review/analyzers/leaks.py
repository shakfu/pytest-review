"""Runtime detection of state a test leaves behind.

This is the one class of defect that static analysis cannot reach. A test can
leak process state through a helper, a fixture, or a library call, with nothing
in its own source to give it away. Because the plugin runs inside pytest, it can
simply look at the process before and after.

The comparison happens *after teardown*, not after the test body: fixtures like
``monkeypatch`` undo their changes during teardown, and reporting those would
flag the correct way of doing things.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    DynamicAnalyzer,
    Issue,
    Severity,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


class StateLeakAnalyzer(DynamicAnalyzer):
    """Detects process state a test changed and never restored."""

    name = "leaks"
    description = "Detects process state left behind after a test finishes"
    category = "isolation"

    # pytest maintains this itself around every test; it is not a leak.
    _IGNORED_ENV = frozenset({"PYTEST_CURRENT_TEST"})

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        self._snapshots: dict[str, tuple[str, dict[str, str], list[str]]] = {}
        self._results: list[AnalyzerResult] = []

    @staticmethod
    def _snapshot() -> tuple[str, dict[str, str], list[str]]:
        try:
            cwd = os.getcwd()
        except OSError:  # cwd deleted underneath us -- itself a leak, but unreadable
            cwd = ""
        return cwd, dict(os.environ), list(sys.path)

    def on_test_start(self, test_id: str) -> None:
        self._snapshots[test_id] = self._snapshot()

    def on_test_end(self, test_id: str, passed: bool, duration: float) -> None:
        """No-op: the comparison must wait until fixtures have torn down."""

    def on_test_teardown(self, test_id: str) -> None:
        """Compare the process against the snapshot taken before the test."""
        before = self._snapshots.pop(test_id, None)
        if before is None:
            return
        old_cwd, old_env, old_path = before
        new_cwd, new_env, new_path = self._snapshot()

        result = AnalyzerResult(analyzer_name=self.name)

        if old_cwd and new_cwd and old_cwd != new_cwd:
            result.add_issue(
                Issue(
                    rule="leaks.cwd",
                    message=(
                        f"Test changed the working directory and did not restore it "
                        f"({old_cwd} -> {new_cwd})"
                    ),
                    severity=Severity.WARNING,
                    test_name=test_id,
                    suggestion="Use the monkeypatch.chdir or tmp_path fixture",
                )
            )

        changed = self._env_changes(old_env, new_env)
        if changed:
            shown = ", ".join(sorted(changed)[:5])
            more = f" (+{len(changed) - 5} more)" if len(changed) > 5 else ""
            result.add_issue(
                Issue(
                    rule="leaks.env",
                    message=f"Test left os.environ modified: {shown}{more}",
                    severity=Severity.WARNING,
                    test_name=test_id,
                    suggestion="Use monkeypatch.setenv/delenv, which restores on teardown",
                )
            )

        if old_path != new_path:
            result.add_issue(
                Issue(
                    rule="leaks.sys_path",
                    message="Test left sys.path modified",
                    severity=Severity.WARNING,
                    test_name=test_id,
                    suggestion="Use monkeypatch.syspath_prepend, which restores on teardown",
                )
            )

        if result.issues:
            self._results.append(result)

    def _env_changes(self, old: dict[str, str], new: dict[str, str]) -> set[str]:
        keys = (set(old) | set(new)) - self._IGNORED_ENV
        return {k for k in keys if old.get(k) != new.get(k)}

    def get_results(self) -> list[AnalyzerResult]:
        return self._results
