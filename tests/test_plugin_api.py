"""Tests for the third-party analyzer plugin API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pytest_review.analyzers.base import (
    AnalyzerResult,
    DynamicAnalyzer,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)
from pytest_review.config import ReviewConfig
from pytest_review.plugin import _discover_entry_point_analyzers
from pytest_review.scoring import ScoringEngine


# ---------------------------------------------------------------------------
# Dummy analyzers used by tests
# ---------------------------------------------------------------------------

class DummyStaticAnalyzer(StaticAnalyzer):
    """A minimal static analyzer for testing the plugin API."""

    name = "dummy-static"
    description = "Dummy static analyzer"
    category = "clarity"

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        result.add_issue(
            Issue(
                rule="dummy-static.always",
                message="Dummy issue",
                severity=Severity.INFO,
                file_path=test.file_path,
                line=test.line,
                test_name=test.name,
            )
        )


class DummyDynamicAnalyzer(DynamicAnalyzer):
    """A minimal dynamic analyzer for testing the plugin API."""

    name = "dummy-dynamic"
    description = "Dummy dynamic analyzer"
    category = "performance"

    def on_test_start(self, test_name: str) -> None:
        pass

    def on_test_end(self, test_name: str, passed: bool, duration: float) -> None:
        pass

    def get_results(self) -> list[AnalyzerResult]:
        return []


class NoCategoryAnalyzer(StaticAnalyzer):
    """Analyzer without a category -- should not break scoring."""

    name = "no-category"
    description = "No category"

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        result.add_issue(
            Issue(
                rule="no-category.test",
                message="Uncategorized issue",
                severity=Severity.WARNING,
                file_path=test.file_path,
                line=test.line,
                test_name=test.name,
            )
        )


# ---------------------------------------------------------------------------
# Fake entry point for mocking importlib.metadata
# ---------------------------------------------------------------------------

class _FakeEntryPoint:
    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


class _BrokenEntryPoint:
    name = "broken-ep"

    def load(self) -> type:
        raise ImportError("simulated import failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzerCategoryAttribute:
    """Verify the category class attribute on Analyzer."""

    def test_default_category_is_empty(self) -> None:
        config = ReviewConfig()
        a = DummyStaticAnalyzer(config)
        # Explicitly set
        assert a.category == "clarity"

    def test_builtin_analyzers_have_empty_category(self) -> None:
        """Built-in analyzers rely on ANALYZER_CATEGORIES, not the attribute."""
        from pytest_review.analyzers import AssertionsAnalyzer

        config = ReviewConfig()
        a = AssertionsAnalyzer(config)
        assert a.category == ""


class TestDiscoverEntryPointAnalyzers:
    """Test entry-point-based analyzer discovery."""

    def test_discovers_static_analyzer(self) -> None:
        fake_eps = [_FakeEntryPoint("dummy", DummyStaticAnalyzer)]
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            discovered = _discover_entry_point_analyzers()
        assert "dummy-static" in discovered
        assert discovered["dummy-static"] is DummyStaticAnalyzer

    def test_discovers_dynamic_analyzer(self) -> None:
        fake_eps = [_FakeEntryPoint("dummy-dyn", DummyDynamicAnalyzer)]
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            discovered = _discover_entry_point_analyzers()
        assert "dummy-dynamic" in discovered
        assert discovered["dummy-dynamic"] is DummyDynamicAnalyzer

    def test_skips_non_analyzer_class(self) -> None:
        class NotAnAnalyzer:
            name = "not-an-analyzer"

        fake_eps = [_FakeEntryPoint("bad", NotAnAnalyzer)]
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            discovered = _discover_entry_point_analyzers()
        assert len(discovered) == 0

    def test_warns_on_broken_entry_point(self) -> None:
        fake_eps = [_BrokenEntryPoint()]
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            with pytest.warns(UserWarning, match="failed to load analyzer entry point"):
                _discover_entry_point_analyzers()

    def test_empty_when_no_entry_points(self) -> None:
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=[],
        ):
            discovered = _discover_entry_point_analyzers()
        assert discovered == {}


class TestScoringWithExtraCategories:
    """Test that ScoringEngine handles third-party analyzer categories."""

    def test_extra_category_integrates_into_scoring(self) -> None:
        results = [
            AnalyzerResult(
                analyzer_name="dummy-static",
                issues=[
                    Issue(
                        rule="dummy-static.always",
                        message="Dummy",
                        severity=Severity.WARNING,
                    ),
                ],
            ),
        ]
        engine = ScoringEngine(extra_categories={"dummy-static": "clarity"})
        breakdown = engine.calculate_score(results, total_tests=10)
        # The issue should contribute to the clarity category
        clarity = next(c for c in breakdown.categories if c.name == "clarity")
        assert clarity.issue_count == 1

    def test_unknown_analyzer_excluded_from_scoring(self) -> None:
        results = [
            AnalyzerResult(
                analyzer_name="unknown",
                issues=[
                    Issue(
                        rule="unknown.test",
                        message="Unknown",
                        severity=Severity.WARNING,
                    ),
                ],
            ),
        ]
        engine = ScoringEngine()
        breakdown = engine.calculate_score(results, total_tests=10)
        # Issue counted in totals but not in any category
        assert breakdown.total_issues == 1
        total_category_issues = sum(c.issue_count for c in breakdown.categories)
        assert total_category_issues == 0

    def test_no_extra_categories_uses_builtin_only(self) -> None:
        engine = ScoringEngine()
        assert engine._categories == ScoringEngine.ANALYZER_CATEGORIES

    def test_extra_categories_merged(self) -> None:
        engine = ScoringEngine(extra_categories={"custom": "isolation"})
        assert engine._categories["custom"] == "isolation"
        # Built-ins still present
        assert engine._categories["assertions"] == "assertions"


class TestPluginAPIIntegration:
    """End-to-end tests using pytester with mocked entry points."""

    def test_custom_static_analyzer_issues_appear(
        self, pytester: pytest.Pytester
    ) -> None:
        """A discovered static analyzer's issues show in the report."""
        fake_eps = [_FakeEntryPoint("dummy", DummyStaticAnalyzer)]
        pytester.makepyfile("""
            def test_validates_something_reasonable():
                assert 1 + 1 == 2
        """)
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            result = pytester.runpytest(
                "--review", "--review-min-severity=info", "--review-no-cache"
            )
        output = result.stdout.str()
        assert "Dummy issue" in output

    def test_custom_analyzer_respects_review_exclude(
        self, pytester: pytest.Pytester
    ) -> None:
        """--review-exclude can suppress a third-party analyzer."""
        fake_eps = [_FakeEntryPoint("dummy", DummyStaticAnalyzer)]
        pytester.makepyfile("""
            def test_validates_something_reasonable():
                assert 1 + 1 == 2
        """)
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            result = pytester.runpytest(
                "--review",
                "--review-exclude=dummy-static",
                "--review-min-severity=info",
                "--review-no-cache",
            )
        output = result.stdout.str()
        assert "Dummy issue" not in output

    def test_custom_analyzer_respects_review_only(
        self, pytester: pytest.Pytester
    ) -> None:
        """--review-only can select only the third-party analyzer."""
        fake_eps = [_FakeEntryPoint("dummy", DummyStaticAnalyzer)]
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            result = pytester.runpytest(
                "--review",
                "--review-only=dummy-static",
                "--review-min-severity=info",
                "--review-no-cache",
            )
        output = result.stdout.str()
        # Dummy issue present, but built-in trivial assertion issue is not
        assert "Dummy issue" in output
        assert "Trivial assertion" not in output

    def test_custom_analyzer_config_from_pyproject(
        self, pytester: pytest.Pytester
    ) -> None:
        """Config for a custom analyzer flows through pyproject.toml."""
        fake_eps = [_FakeEntryPoint("dummy", DummyStaticAnalyzer)]
        pytester.makepyfile("""
            def test_validates_something_reasonable():
                assert 1 + 1 == 2
        """)
        pytester.makepyprojecttoml("""
            [tool.pytest-review.analyzers.dummy-static]
            enabled = false
        """)
        with patch(
            "pytest_review.plugin.importlib.metadata.entry_points",
            return_value=fake_eps,
        ):
            result = pytester.runpytest(
                "--review", "--review-min-severity=info", "--review-no-cache"
            )
        output = result.stdout.str()
        # Analyzer disabled via config -- its issue should not appear
        assert "Dummy issue" not in output
