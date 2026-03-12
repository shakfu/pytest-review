"""Tests for --review-diff mode."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from pytest_review.plugin import ReviewPlugin


class TestGetChangedFiles:
    """Unit tests for _get_changed_files."""

    def _make_plugin(self) -> ReviewPlugin:
        """Create a minimal ReviewPlugin with a mock config."""

        class FakeConfig:
            def getoption(self, name: str, default: object = None) -> object:
                return default

        return ReviewPlugin(FakeConfig())  # type: ignore[arg-type]

    def test_auto_detects_main_branch(self) -> None:
        plugin = self._make_plugin()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                if cmd[3] == "main":
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                return subprocess.CompletedProcess(cmd, 1, "", "error")
            if cmd[:3] == ["git", "diff", "--name-only"]:
                return subprocess.CompletedProcess(cmd, 0, "tests/test_foo.py\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")

        with patch("pytest_review.plugin.subprocess.run", side_effect=fake_run):
            result = plugin._get_changed_files("auto")

        assert result is not None
        assert any(p.name == "test_foo.py" for p in result)

    def test_auto_falls_back_to_master(self) -> None:
        plugin = self._make_plugin()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                if cmd[3] == "master":
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                return subprocess.CompletedProcess(cmd, 1, "", "error")
            if cmd[:3] == ["git", "diff", "--name-only"]:
                return subprocess.CompletedProcess(cmd, 0, "tests/test_bar.py\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")

        with patch("pytest_review.plugin.subprocess.run", side_effect=fake_run):
            result = plugin._get_changed_files("auto")

        assert result is not None
        assert any(p.name == "test_bar.py" for p in result)

    def test_auto_warns_when_no_branch_found(self) -> None:
        plugin = self._make_plugin()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, "", "not found")

        with (
            patch("pytest_review.plugin.subprocess.run", side_effect=fake_run),
            pytest.warns(UserWarning, match="could not detect base branch"),
        ):
            result = plugin._get_changed_files("auto")

        assert result is None

    def test_explicit_base_branch(self) -> None:
        plugin = self._make_plugin()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["git", "diff", "--name-only"]:
                assert cmd[3] == "develop...HEAD"
                return subprocess.CompletedProcess(cmd, 0, "src/foo.py\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")

        with patch("pytest_review.plugin.subprocess.run", side_effect=fake_run):
            result = plugin._get_changed_files("develop")

        assert result is not None
        assert any(p.name == "foo.py" for p in result)

    def test_git_diff_failure_returns_none(self) -> None:
        plugin = self._make_plugin()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, "", "fatal: bad revision")

        with (
            patch("pytest_review.plugin.subprocess.run", side_effect=fake_run),
            pytest.warns(UserWarning, match="git diff failed"),
        ):
            result = plugin._get_changed_files("main")

        assert result is None


class TestDiffModeIntegration:
    """Integration tests using pytester."""

    def test_diff_option_is_accepted(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_diff_option_accepted_by_plugin():
                assert True
        """)
        # --review-diff with explicit branch; even if diff fails, it should
        # fall back gracefully and analyze all tests
        result = pytester.runpytest("--review", "--review-diff=main")
        result.assert_outcomes(passed=1)
