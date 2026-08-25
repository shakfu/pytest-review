"""Tests for incremental caching and parallel analysis features."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity
from pytest_review.config import ReviewConfig
from pytest_review.plugin import (
    ReviewPlugin,
    _deserialize_results,
    _get_static_analyzer_classes,
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

    def test_round_trip_empty_results(self) -> None:
        serialized = _serialize_results([])
        restored = _deserialize_results(serialized)
        assert restored == []


    def test_round_trip_with_no_file_path(self) -> None:
        original = [
            AnalyzerResult(
                analyzer_name="smells",
                issues=[
                    Issue(
                        rule="smells.early_return",
                        message="Test contains a return",
                        severity=Severity.WARNING,
                    ),
                ],
            )
        ]
        serialized = _serialize_results(original)
        restored = _deserialize_results(serialized)

        assert restored[0].issues[0].file_path is None
        assert restored[0].issues[0].line is None

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
                analyzer_name="isolation",
                issues=[
                    Issue(
                        rule="isolation.global_modification",
                        message="Modifies global state",
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
        assert restored[1].analyzer_name == "isolation"
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
                        rule="patterns.sleep_in_test",
                        message="time.sleep() in test",
                        severity=Severity.WARNING,
                        file_path=Path("/a/b.py"),
                        line=1,
                    ),
                ],
            )
        ]
        serialized = _serialize_results(original)

        assert json.loads(json.dumps(serialized)) == serialized


class TestIncrementalCache:
    """Test that caching skips re-analysis of unchanged files."""

    def test_second_run_uses_cache(self, pytester: pytest.Pytester) -> None:
        """Running twice with the same file should use cached results."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        # First run populates cache
        result1 = pytester.runpytest("--review", "--review-min-score=1")
        result1.assert_outcomes(passed=1)
        assert "pytest-review" in result1.stdout.str()

        # Second run should produce identical output (from cache)
        result2 = pytester.runpytest("--review", "--review-min-score=1")
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
        result1 = pytester.runpytest("--review", "--review-min-score=1")
        assert "Trivial assertion" in result1.stdout.str()

        # Modify the file to fix the trivial assertion
        test_file.write_text(
            'def test_validates_result_matches_expected():\n'
            '    result = 1 + 1\n'
            '    assert result == 2\n',
            encoding="utf-8",
        )
        result2 = pytester.runpytest("--review", "--review-min-score=1")
        # The trivial assertion issue should no longer appear
        assert "Trivial assertion" not in result2.stdout.str()

    def test_identical_files_keep_separate_cache_entries(
        self, pytester: pytest.Pytester
    ) -> None:
        """Files with identical contents must not share a cache entry.

        The key must include the file path; otherwise the second run serves one
        file's cached issues for the other and reports the wrong path.
        """
        body = """
            def test_x():
                assert True
        """
        pytester.makepyfile(test_alpha=body, test_beta=body)

        first = pytester.runpytest("--review", "--review-min-score=1")
        first.assert_outcomes(passed=2)

        second = pytester.runpytest("--review", "--review-min-score=1")
        second.assert_outcomes(passed=2)

        for result in (first, second):
            output = result.stdout.str()
            assert "test_alpha.py" in output
            assert "test_beta.py" in output
            # Exactly one trivial-assertion issue per file, not two for one file
            assert output.count("test_alpha.py:2 [test_x] Trivial assertion") == 1
            assert output.count("test_beta.py:2 [test_x] Trivial assertion") == 1

    def test_cached_run_matches_uncached_run(self, pytester: pytest.Pytester) -> None:
        """Identical-content files score the same with and without the cache."""
        body = """
            def test_x():
                assert True
        """
        pytester.makepyfile(test_alpha=body, test_beta=body)

        def extract_score(out: str) -> str:
            for line in out.splitlines():
                if "Overall Score:" in line:
                    return line.strip()
            raise AssertionError("Overall Score line missing from output")

        uncached = pytester.runpytest("--review", "--review-no-cache", "--review-min-score=1")
        pytester.runpytest("--review", "--review-min-score=1")  # populate cache
        cached = pytester.runpytest("--review", "--review-min-score=1")

        assert extract_score(cached.stdout.str()) == extract_score(uncached.stdout.str())

    def test_runs_without_cacheprovider_plugin(self, pytester: pytest.Pytester) -> None:
        """``-p no:cacheprovider`` removes ``config.cache``; review must not crash."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        result = pytester.runpytest("--review", "-p", "no:cacheprovider")
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert "AttributeError" not in output
        assert "Trivial assertion" in output

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


class TestCacheKeyCoversAnalysisInputs:
    """The cache key must cover everything that can change findings.

    Keying only on file contents and *explicitly set* options means an upgrade,
    or any change to a rule's default threshold, silently serves the previous
    version's findings for every unchanged file until someone runs
    ``--cache-clear``. Nothing warns that the output is stale.
    """

    def test_resolved_settings_include_unset_defaults(self) -> None:
        """Defaults must appear in the key material, not just overridden values."""
        resolved = ReviewPlugin._resolved_analyzer_settings(ReviewConfig())

        smells = resolved["get_smells_config"]
        assert "max_assertions_without_message" in smells
        assert smells["max_assertions_without_message"] == (
            ReviewConfig().get_smells_config().max_assertions_without_message
        )

    def test_resolved_settings_track_a_changed_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing a default must change the key material."""
        before = ReviewPlugin._resolved_analyzer_settings(ReviewConfig())

        original = ReviewConfig.get_smells_config

        def patched(self: ReviewConfig) -> object:
            cfg = original(self)
            cfg.max_assertions_without_message += 1
            return cfg

        monkeypatch.setattr(ReviewConfig, "get_smells_config", patched)
        after = ReviewPlugin._resolved_analyzer_settings(ReviewConfig())

        assert before != after

    @staticmethod
    def _hash_with_default_config() -> str:
        """``_get_config_hash`` for a default config, without a live session."""
        plugin = object.__new__(ReviewPlugin)
        plugin.review_config = ReviewConfig()
        return plugin._get_config_hash(["smells"])

    def test_config_hash_changes_when_a_rule_default_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resolved defaults must reach the key, not merely be computable.

        This is the end of the wiring the other tests only check in pieces: it
        fails if ``_get_config_hash`` stops folding the resolved settings in,
        which is the exact shape of the original bug.
        """
        before = self._hash_with_default_config()

        original = ReviewConfig.get_smells_config

        def patched(self: ReviewConfig) -> object:
            cfg = original(self)
            cfg.max_assertions_without_message += 1
            return cfg

        monkeypatch.setattr(ReviewConfig, "get_smells_config", patched)

        assert self._hash_with_default_config() != before

    def test_config_hash_changes_when_the_analyzer_set_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The analyzer implementations must reach the key too."""
        before = self._hash_with_default_config()

        classes = dict(_get_static_analyzer_classes())
        classes.pop(sorted(classes)[0])
        monkeypatch.setattr(
            "pytest_review.plugin._get_static_analyzer_classes", lambda: classes
        )

        assert self._hash_with_default_config() != before

    def test_implementation_hash_is_stable_and_covers_the_analyzer_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The analyzer implementations participate in the key."""
        baseline = ReviewPlugin._analyzer_implementation_hash()
        assert baseline == ReviewPlugin._analyzer_implementation_hash()

        classes = dict(_get_static_analyzer_classes())
        classes.pop(sorted(classes)[0])
        monkeypatch.setattr(
            "pytest_review.plugin._get_static_analyzer_classes", lambda: classes
        )

        assert ReviewPlugin._analyzer_implementation_hash() != baseline


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
