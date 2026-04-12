"""Tests for incremental caching and parallel analysis features."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity
from pytest_review.plugin import (
    _deserialize_results,
    _serialize_results,
)


class TestResultSerialization:
    """Test round-trip serialization of analysis results."""

    def test_round_trip_preserves_issues(self) -> None:
        original = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue(
                        rule="assertions.missing",
                        message="Test has no assertions",
                        severity=Severity.ERROR,
                        file_path=Path("/tmp/test_example.py"),
                        line=10,
                        test_name="test_empty",
                        suggestion="Add at least one assertion",
                    ),
                ],
                score=80.0,
                metadata={"assertion_count": 0},
            )
        ]
        serialized = _serialize_results(original)
        restored = _deserialize_results(serialized)

        assert len(restored) == 1
        assert restored[0].analyzer_name == "assertions"
        assert restored[0].score == 80.0
        assert len(restored[0].issues) == 1

        issue = restored[0].issues[0]
        assert issue.rule == "assertions.missing"
        assert issue.severity == Severity.ERROR
        assert issue.file_path == Path("/tmp/test_example.py")
        assert issue.line == 10
        assert issue.test_name == "test_empty"
        assert issue.suggestion == "Add at least one assertion"

    def test_round_trip_with_no_file_path(self) -> None:
        original = [
            AnalyzerResult(
                analyzer_name="naming",
                issues=[
                    Issue(
                        rule="naming.too_short",
                        message="Name is too short",
                        severity=Severity.INFO,
                    ),
                ],
            )
        ]
        serialized = _serialize_results(original)
        restored = _deserialize_results(serialized)

        assert restored[0].issues[0].file_path is None
        assert restored[0].issues[0].line is None

    def test_round_trip_empty_results(self) -> None:
        serialized = _serialize_results([])
        restored = _deserialize_results(serialized)
        assert restored == []

    def test_round_trip_multiple_results(self) -> None:
        original = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue(
                        rule="assertions.trivial",
                        message="Trivial assertion",
                        severity=Severity.ERROR,
                        file_path=Path("/test.py"),
                        line=5,
                    ),
                ],
            ),
            AnalyzerResult(
                analyzer_name="naming",
                issues=[
                    Issue(
                        rule="naming.non_descriptive",
                        message="Non-descriptive name",
                        severity=Severity.WARNING,
                        file_path=Path("/test.py"),
                        line=5,
                        test_name="test_foo",
                    ),
                ],
            ),
        ]
        serialized = _serialize_results(original)
        restored = _deserialize_results(serialized)

        assert len(restored) == 2
        assert restored[0].analyzer_name == "assertions"
        assert restored[1].analyzer_name == "naming"
        assert restored[0].issues[0].severity == Severity.ERROR
        assert restored[1].issues[0].severity == Severity.WARNING

    def test_serialized_is_json_compatible(self) -> None:
        """Serialized results must be storable in pytest's JSON-based cache."""
        import json

        original = [
            AnalyzerResult(
                analyzer_name="patterns",
                issues=[
                    Issue(
                        rule="patterns.print_statement",
                        message="print() in test",
                        severity=Severity.INFO,
                        file_path=Path("/a/b.py"),
                        line=1,
                        test_name="test_x",
                        suggestion="Remove print",
                    ),
                ],
                score=95.0,
                metadata={"pattern_issues": 1},
            )
        ]
        serialized = _serialize_results(original)
        # Must not raise
        dumped = json.dumps(serialized)
        loaded = json.loads(dumped)
        restored = _deserialize_results(loaded)
        assert restored[0].issues[0].rule == "patterns.print_statement"


class TestIncrementalCache:
    """Test that caching skips re-analysis of unchanged files."""

    def test_second_run_uses_cache(self, pytester: pytest.Pytester) -> None:
        """Running twice with the same file should use cached results."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        # First run populates cache
        result1 = pytester.runpytest("--review")
        result1.assert_outcomes(passed=1)
        assert "pytest-review" in result1.stdout.str()

        # Second run should produce identical output (from cache)
        result2 = pytester.runpytest("--review")
        result2.assert_outcomes(passed=1)
        assert "pytest-review" in result2.stdout.str()

        def extract_score(out: str) -> str:
            for line in out.splitlines():
                if "Overall Score:" in line:
                    return line.strip()
            return ""

        assert extract_score(result1.stdout.str()) == extract_score(result2.stdout.str())

    def test_cache_invalidated_on_file_change(self, pytester: pytest.Pytester) -> None:
        """Modifying a file should invalidate the cache for that file."""
        test_file = pytester.makepyfile("""
            def test_1():
                assert True
        """)
        result1 = pytester.runpytest("--review")
        assert "Trivial assertion" in result1.stdout.str()

        # Modify the file to fix the trivial assertion
        test_file.write_text(
            'def test_validates_result_matches_expected():\n'
            '    result = 1 + 1\n'
            '    assert result == 2\n',
            encoding="utf-8",
        )
        result2 = pytester.runpytest("--review")
        # The trivial assertion issue should no longer appear
        assert "Trivial assertion" not in result2.stdout.str()

    def test_no_cache_flag_disables_caching(self, pytester: pytest.Pytester) -> None:
        """--review-no-cache should still produce correct results."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        result.assert_outcomes(passed=1)
        assert "pytest-review" in result.stdout.str()
        assert "Trivial assertion" in result.stdout.str()


class TestParallelAnalysis:
    """Test --review-workers option."""

    def test_workers_1_runs_sequentially(self, pytester: pytest.Pytester) -> None:
        """--review-workers=1 forces sequential analysis."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        result = pytester.runpytest("--review", "--review-workers=1", "--review-no-cache")
        result.assert_outcomes(passed=1)
        assert "pytest-review" in result.stdout.str()
        assert "Trivial assertion" in result.stdout.str()

    def test_workers_option_accepted(self, pytester: pytest.Pytester) -> None:
        """--review-workers is accepted without error."""
        pytester.makepyfile("""
            def test_validates_result_matches_expected():
                assert 1 + 1 == 2
        """)
        result = pytester.runpytest("--review", "--review-workers=2", "--review-no-cache")
        result.assert_outcomes(passed=1)
        assert "pytest-review" in result.stdout.str()

    def test_parallel_produces_same_results(self, pytester: pytest.Pytester) -> None:
        """Parallel and sequential analysis should produce identical scores."""
        pytester.makepyfile(
            test_a="""
            def test_1():
                assert True
        """,
            test_b="""
            def test_validates_connection_is_established():
                conn = {"status": "ok"}
                assert conn["status"] == "ok"
        """,
        )

        sequential = pytester.runpytest(
            "--review", "--review-workers=1", "--review-no-cache"
        )
        # Force parallel even for a small suite
        parallel = pytester.runpytest(
            "--review", "--review-workers=2", "--review-no-cache"
        )

        def extract_score(out: str) -> str:
            for line in out.splitlines():
                if "Overall Score:" in line:
                    return line.strip()
            return ""

        assert extract_score(sequential.stdout.str()) == extract_score(
            parallel.stdout.str()
        )
