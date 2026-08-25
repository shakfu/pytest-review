"""Tests for runtime state-leak detection.

These run through ``pytester`` rather than against the analyzer directly: the
whole point of the rule is that it observes the real process across a real test
lifecycle, and the thing most likely to break it -- comparing state before
fixtures have torn down -- only shows up end to end.
"""

from __future__ import annotations

import pytest


class TestStateLeakDetection:
    def test_detects_env_leak(
        self, pytester: pytest.Pytester, restore_environ: None
    ) -> None:
        pytester.makepyfile("""
            import os

            def test_leaks():
                os.environ["LEAKED_TOKEN"] = "x"
                assert os.environ["LEAKED_TOKEN"] == "x"
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert "leaks.env" in result.stdout.str() or "os.environ modified" in result.stdout.str()

    def test_monkeypatch_is_not_a_leak(self, pytester: pytest.Pytester) -> None:
        """The correct idiom must stay silent.

        ``monkeypatch`` restores state during teardown, so a detector that
        compared at the end of the call phase would report every correct use.
        """
        pytester.makepyfile("""
            import os

            def test_safe(monkeypatch):
                monkeypatch.setenv("SAFE_TOKEN", "x")
                assert os.environ["SAFE_TOKEN"] == "x"
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert "os.environ modified" not in result.stdout.str()

    def test_detects_cwd_leak(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import os

            def test_leaks_cwd(tmp_path):
                os.chdir(tmp_path)
                assert os.getcwd() == str(tmp_path)
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert "working directory" in result.stdout.str()

    def test_monkeypatch_chdir_is_not_a_leak(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import os

            def test_safe_chdir(monkeypatch, tmp_path):
                monkeypatch.chdir(tmp_path)
                assert os.getcwd() == str(tmp_path)
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert "working directory" not in result.stdout.str()

    def test_detects_a_leak_caused_inside_a_helper(
        self, pytester: pytest.Pytester, restore_environ: None
    ) -> None:
        """The case static analysis cannot reach.

        Nothing in the test body mentions ``os.environ``; the mutation happens
        one call away. Only observing the real process finds it.
        """
        pytester.makepyfile("""
            import os

            def _configure():
                os.environ["LEAKED_BY_HELPER"] = "1"

            def test_leaks_via_helper():
                _configure()
                assert os.environ["LEAKED_BY_HELPER"] == "1"
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert "LEAKED_BY_HELPER" in result.stdout.str()

    def test_clean_test_reports_no_leak(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_adds_numbers_correctly():
                assert 1 + 1 == 2
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        out = result.stdout.str()
        assert "os.environ modified" not in out
        assert "working directory" not in out
        assert "sys.path" not in out
