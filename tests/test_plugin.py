"""Tests for the pytest plugin integration."""

from __future__ import annotations

import pytest


class TestPluginOptions:
    """Test command line option parsing."""

    def test_review_option_default_disabled(self, pytester: pytest.Pytester) -> None:
        """Plugin is disabled by default."""
        pytester.makepyfile("""
            def test_example():
                assert True
        """)
        result = pytester.runpytest()
        result.assert_outcomes(passed=1)
        # Review header should not appear
        assert "pytest-review" not in result.stdout.str()

    def test_review_option_enables_plugin(self, pytester: pytest.Pytester) -> None:
        """--review flag enables the plugin."""
        pytester.makepyfile("""
            def test_example():
                assert True
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=1)
        # Review header should appear
        assert "pytest-review" in result.stdout.str()
        assert "Test Quality Report" in result.stdout.str()

    def test_review_shows_summary(self, pytester: pytest.Pytester) -> None:
        """Review shows summary with test count."""
        pytester.makepyfile("""
            def test_one():
                assert True

            def test_two():
                assert True
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=2)
        assert "Tests analyzed: 2" in result.stdout.str()

    def test_review_skip_marker(self, pytester: pytest.Pytester) -> None:
        """Tests marked with review_skip are excluded."""
        pytester.makepyfile("""
            import pytest

            def test_included():
                assert True

            @pytest.mark.review_skip
            def test_excluded():
                assert True
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=2)
        # Only one test should be analyzed
        assert "Tests analyzed: 1" in result.stdout.str()


class TestPluginOutput:
    """Test plugin output formatting."""

    def test_shows_quality_excellent_when_no_issues(self, pytester: pytest.Pytester) -> None:
        """Shows excellent quality when no issues found."""
        # Use a well-formed test that passes all analyzers
        pytester.makepyfile("""
            def test_user_authentication_succeeds_with_valid_credentials():
                user_id = 123
                expected_id = 123
                assert user_id == expected_id
        """)
        result = pytester.runpytest("--review")
        assert "No quality issues found" in result.stdout.str()
        assert "Quality: EXCELLENT" in result.stdout.str()

    def test_shows_overall_score(self, pytester: pytest.Pytester) -> None:
        """Shows overall score in output."""
        pytester.makepyfile("""
            def test_calculation_returns_expected_result():
                result = 1 + 1
                assert result == 2
        """)
        result = pytester.runpytest("--review")
        assert "Overall Score:" in result.stdout.str()
        assert "/100" in result.stdout.str()

    def test_detects_quality_issues(self, pytester: pytest.Pytester) -> None:
        """Shows issues when tests have quality problems."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        result = pytester.runpytest("--review")
        # Should detect issues with this test
        assert "Quality: NEEDS IMPROVEMENT" in result.stdout.str()
        output = result.stdout.str()
        assert "assertions.trivial" in output or "Trivial assertion" in output
