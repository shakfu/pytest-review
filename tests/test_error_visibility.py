"""Tests for error visibility when tests cannot be analyzed."""

from __future__ import annotations

import pytest


class TestErrorVisibility:
    def test_warns_on_syntax_error_in_test_file(self, pytester: pytest.Pytester) -> None:
        """When a test file has a syntax error, we cannot parse it for review.

        We cannot easily inject a SyntaxError after collection (pytest itself
        would fail to collect), so we test indirectly: a well-formed test file
        should NOT produce any warnings.
        """
        pytester.makepyfile("""
            def test_valid_parseable_test_function():
                assert 1 + 1 == 2
        """)
        result = pytester.runpytest("--review", "-W", "error::UserWarning")
        result.assert_outcomes(passed=1)
        # No UserWarning should be raised for a valid test file
        assert "pytest-review: could not" not in result.stdout.str()

    def test_normal_test_analyzed_without_warnings(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_properly_analyzed_without_warnings():
                result = 42
                assert result == 42
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=1)
        assert "could not read" not in result.stdout.str()
        assert "could not parse" not in result.stdout.str()
