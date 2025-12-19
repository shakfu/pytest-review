"""Dynamic data collection during test execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestExecutionData:
    """Data collected during test execution."""

    test_name: str
    node_id: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    passed: bool = True
    exception: str | None = None
    captured_globals_before: dict[str, Any] = field(default_factory=dict)
    captured_globals_after: dict[str, Any] = field(default_factory=dict)
    modified_globals: list[str] = field(default_factory=list)
    fixtures_used: list[str] = field(default_factory=list)


class DynamicCollector:
    """Collects runtime data during test execution."""

    def __init__(self) -> None:
        self._current_test: TestExecutionData | None = None
        self._completed_tests: list[TestExecutionData] = []
        self._global_snapshots: dict[str, dict[str, Any]] = {}

    def start_test(self, node_id: str, test_name: str) -> None:
        """Called when a test starts."""
        self._current_test = TestExecutionData(
            test_name=test_name,
            node_id=node_id,
            start_time=time.perf_counter(),
        )

    def end_test(self, passed: bool, exception: str | None = None) -> None:
        """Called when a test ends."""
        if self._current_test is None:
            return

        self._current_test.end_time = time.perf_counter()
        self._current_test.duration_ms = (
            self._current_test.end_time - self._current_test.start_time
        ) * 1000
        self._current_test.passed = passed
        self._current_test.exception = exception

        self._completed_tests.append(self._current_test)
        self._current_test = None

    def record_fixtures(self, fixture_names: list[str]) -> None:
        """Record fixtures used by current test."""
        if self._current_test:
            self._current_test.fixtures_used = fixture_names

    def get_completed_tests(self) -> list[TestExecutionData]:
        """Get all completed test execution data."""
        return self._completed_tests

    def get_test_by_name(self, test_name: str) -> TestExecutionData | None:
        """Get execution data for a specific test."""
        for test in self._completed_tests:
            if test.test_name == test_name:
                return test
        return None

    def clear(self) -> None:
        """Clear all collected data."""
        self._current_test = None
        self._completed_tests = []
        self._global_snapshots = {}
