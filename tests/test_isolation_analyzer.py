"""Tests for the isolation analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.analyzers.isolation import IsolationStaticAnalyzer
from pytest_review.config import ReviewConfig


def make_test_info(source: str, name: str = "test_example") -> TestItemInfo:
    """Helper to create TestItemInfo from source code."""
    tree = ast.parse(source)
    func_node = tree.body[0]
    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return TestItemInfo(
        name=name,
        file_path=Path("test_file.py"),
        line=1,
        node=func_node,
        source=source,
    )


class TestIsolationStaticAnalyzer:
    def test_detects_global_keyword(self) -> None:
        source = """
def test_modifies_global():
    global counter
    counter += 1
    assert counter > 0
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_global")

        result = analyzer.analyze(test_info)

        global_issues = [i for i in result.issues if i.rule == "isolation.global_modification"]
        assert len(global_issues) == 1
        assert "global counter" in global_issues[0].message
        assert global_issues[0].severity == Severity.WARNING

    def test_detects_class_attribute_modification(self) -> None:
        source = """
def test_modifies_class_attr():
    cls.shared_state = "modified"
    assert cls.shared_state == "modified"
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_class_attr")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 1
        assert "cls.shared_state" in class_issues[0].message

    def test_detects_uppercase_class_modification(self) -> None:
        source = """
def test_modifies_config():
    Config.DEBUG = True
    assert Config.DEBUG
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_config")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 1
        assert "Config.DEBUG" in class_issues[0].message

    def test_clean_test_passes(self) -> None:
        source = """
def test_clean_isolation():
    local_var = "value"
    result = process(local_var)
    assert result is not None
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_clean_isolation")

        result = analyzer.analyze(test_info)

        # Should have no isolation issues
        isolation_issues = [i for i in result.issues if i.rule.startswith("isolation.")]
        assert len(isolation_issues) == 0

    def test_stores_metadata(self) -> None:
        source = """
def test_with_globals():
    global a, b
    a = 1
    b = 2
    assert a + b == 3
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_globals")

        result = analyzer.analyze(test_info)

        assert result.metadata["global_modifications"] == 2

    def test_instance_attribute_is_allowed(self) -> None:
        source = """
def test_instance_attr(self):
    self.value = 123
    assert self.value == 123
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_instance_attr")

        result = analyzer.analyze(test_info)

        # self.attr modifications are fine (instance, not class)
        # 'self' is a parameter so it's in local scope
        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 0

    def test_detects_lowercase_external_attr_modification(self) -> None:
        source = """
def test_modifies_external():
    settings.DEBUG = True
    assert settings.DEBUG
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_external")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 1
        assert "settings.DEBUG" in class_issues[0].message

    def test_locally_assigned_object_not_flagged(self) -> None:
        source = """
def test_local_object():
    Config = make_config()
    Config.value = 42
    assert Config.value == 42
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_local_object")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 0

    def test_fixture_parameter_not_flagged(self) -> None:
        source = """
def test_with_fixture(db):
    db.state = "ready"
    assert db.state == "ready"
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_fixture")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 0

    def test_detects_os_environ_subscript_mutation(self) -> None:
        source = """
def test_env_mutation():
    import os
    os.environ["MY_VAR"] = "value"
    assert os.environ["MY_VAR"] == "value"
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_env_mutation")

        result = analyzer.analyze(test_info)

        env_issues = [i for i in result.issues if i.rule == "isolation.env_mutation"]
        assert len(env_issues) == 1
        assert "os.environ" in env_issues[0].message
        assert env_issues[0].severity == Severity.WARNING

    def test_detects_os_environ_update_call(self) -> None:
        source = """
def test_env_update():
    import os
    os.environ.update({"KEY": "val"})
    assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_env_update")

        result = analyzer.analyze(test_info)

        env_issues = [i for i in result.issues if i.rule == "isolation.env_mutation"]
        assert len(env_issues) == 1
        assert "update" in env_issues[0].message

    def test_detects_bare_patch_call(self) -> None:
        source = """
def test_bare_patch():
    from unittest.mock import patch
    patch("module.Class.method", return_value=42)
    assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_bare_patch")

        result = analyzer.analyze(test_info)

        patch_issues = [i for i in result.issues if i.rule == "isolation.bare_patch"]
        assert len(patch_issues) == 1
        assert patch_issues[0].severity == Severity.WARNING

    def test_patch_with_context_manager_not_flagged(self) -> None:
        source = """
def test_patch_ctx():
    from unittest.mock import patch
    with patch("module.Class.method", return_value=42):
        assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_patch_ctx")

        result = analyzer.analyze(test_info)

        patch_issues = [i for i in result.issues if i.rule == "isolation.bare_patch"]
        assert len(patch_issues) == 0

    def test_detects_os_chdir(self) -> None:
        source = """
def test_chdir():
    import os
    os.chdir("/tmp")
    assert os.getcwd() == "/tmp"
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_chdir")

        result = analyzer.analyze(test_info)

        process_issues = [i for i in result.issues if i.rule == "isolation.process_mutation"]
        assert len(process_issues) == 1
        assert "os.chdir" in process_issues[0].message
        assert process_issues[0].severity == Severity.WARNING

    def test_detects_sys_path_append(self) -> None:
        source = """
def test_sys_path_append():
    import sys
    sys.path.append("/some/path")
    assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_sys_path_append")

        result = analyzer.analyze(test_info)

        process_issues = [i for i in result.issues if i.rule == "isolation.process_mutation"]
        assert len(process_issues) == 1
        assert "sys.path.append" in process_issues[0].message
        # Ensure it did NOT double-flag as class_attr_modification
        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 0

    def test_detects_sys_path_insert(self) -> None:
        source = """
def test_sys_path_insert():
    import sys
    sys.path.insert(0, "/some/path")
    assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_sys_path_insert")

        result = analyzer.analyze(test_info)

        process_issues = [i for i in result.issues if i.rule == "isolation.process_mutation"]
        assert len(process_issues) == 1
        assert "sys.path.insert" in process_issues[0].message

    def test_detects_sys_path_subscript_assign(self) -> None:
        source = """
def test_sys_path_subscript():
    import sys
    sys.path[0] = "/new/path"
    assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_sys_path_subscript")

        result = analyzer.analyze(test_info)

        process_issues = [i for i in result.issues if i.rule == "isolation.process_mutation"]
        assert len(process_issues) == 1
        assert "sys.path" in process_issues[0].message

    def test_detects_sys_argv_mutation(self) -> None:
        source = """
def test_sys_argv():
    import sys
    sys.argv.append("--flag")
    assert True
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_sys_argv")

        result = analyzer.analyze(test_info)

        process_issues = [i for i in result.issues if i.rule == "isolation.process_mutation"]
        assert len(process_issues) == 1
        assert "sys.argv.append" in process_issues[0].message

    def test_os_environ_read_not_flagged(self) -> None:
        source = """
def test_env_read():
    import os
    val = os.environ.get("HOME")
    assert val is not None
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_env_read")

        result = analyzer.analyze(test_info)

        env_issues = [i for i in result.issues if i.rule == "isolation.env_mutation"]
        assert len(env_issues) == 0


class TestIsolationAnalyzerIntegration:
    """Integration tests using pytester."""

    def test_detects_global_in_real_test(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            counter = 0

            def test_increments_global_counter_problematically():
                global counter
                counter += 1
                assert counter == 1
        """)
        result = pytester.runpytest("--review", "--review-only=isolation")
        result.assert_outcomes(passed=1)
        assert "global" in result.stdout.str().lower()

    def test_clean_test_no_issues(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_properly_isolated_with_local_state():
                local_counter = 0
                local_counter += 1
                assert local_counter == 1
        """)
        result = pytester.runpytest("--review", "--review-only=isolation")
        result.assert_outcomes(passed=1)
        assert "No quality issues found" in result.stdout.str()
