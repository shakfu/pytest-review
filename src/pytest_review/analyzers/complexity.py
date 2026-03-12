"""Analyzer for test complexity."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


class ComplexityVisitor(ast.NodeVisitor):
    """AST visitor that measures code complexity."""

    def __init__(self) -> None:
        self.statement_count = 0
        self.assertion_count = 0
        self.max_depth = 0
        self.cyclomatic_complexity = 1  # Base complexity
        self._current_depth = 0

    def _count_statement(self) -> None:
        """Increment statement counter."""
        self.statement_count += 1

    def _enter_scope(self) -> None:
        """Enter a nested scope."""
        self._current_depth += 1
        self.max_depth = max(self.max_depth, self._current_depth)

    def _exit_scope(self) -> None:
        """Exit a nested scope."""
        self._current_depth -= 1

    # Statement counting
    def visit_Assign(self, node: ast.Assign) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        # Skip docstrings (string constant expressions)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        self._count_statement()
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._count_statement()
        self.assertion_count += 1
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Pass(self, node: ast.Pass) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Break(self, node: ast.Break) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Continue(self, node: ast.Continue) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._count_statement()
        self.generic_visit(node)

    # Cyclomatic complexity - count decision points
    def visit_If(self, node: ast.If) -> None:
        self._count_statement()
        self.cyclomatic_complexity += 1
        # Visit the condition (may contain BoolOp, IfExp, etc.)
        self.visit(node.test)
        self._enter_scope()
        for child in node.body:
            self.visit(child)
        self._exit_scope()
        # Visit orelse without re-dispatching to visit_If for chained elif
        # (the chained If node will be visited directly, incrementing complexity once)
        for child in node.orelse:
            self.visit(child)

    def visit_For(self, node: ast.For) -> None:
        self._count_statement()
        self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_While(self, node: ast.While) -> None:
        self._count_statement()
        self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_With(self, node: ast.With) -> None:
        self._count_statement()
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_Try(self, node: ast.Try) -> None:
        self._count_statement()
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Each 'and'/'or' adds a decision point
        self.cyclomatic_complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        # Ternary expression
        self.cyclomatic_complexity += 1
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._count_statement()
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._count_statement()
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._count_statement()
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)


class ComplexityAnalyzer(StaticAnalyzer):
    """Analyzes test complexity."""

    name = "complexity"
    description = "Checks for overly complex tests"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        typed = config.get_complexity_config()
        self._max_statements = typed.max_statements
        self._max_depth = typed.max_depth
        self._max_complexity = typed.max_complexity

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        visitor = ComplexityVisitor()
        visitor.visit(test.node)

        # Check statement count
        if visitor.statement_count > self._max_statements:
            result.add_issue(
                Issue(
                    rule="complexity.too_many_statements",
                    message=f"Test has {visitor.statement_count} statements "
                    f"(maximum {self._max_statements})",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Break down into smaller, focused tests or extract helper functions",
                )
            )

        # Check nesting depth
        if visitor.max_depth > self._max_depth:
            result.add_issue(
                Issue(
                    rule="complexity.deep_nesting",
                    message=f"Test has nesting depth of {visitor.max_depth} "
                    f"(maximum {self._max_depth})",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Reduce nesting by extracting conditions or using early returns",
                )
            )

        # Check cyclomatic complexity
        if visitor.cyclomatic_complexity > self._max_complexity:
            result.add_issue(
                Issue(
                    rule="complexity.high_cyclomatic",
                    message=f"Test has cyclomatic complexity of {visitor.cyclomatic_complexity} "
                    f"(maximum {self._max_complexity})",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Simplify test logic or split into multiple tests",
                )
            )

        # Check assertion-to-logic ratio
        if (
            visitor.statement_count >= 10
            and visitor.assertion_count > 0
            and visitor.assertion_count / visitor.statement_count < 0.1
        ):
            result.add_issue(
                Issue(
                    rule="complexity.low_assertion_ratio",
                    message=(
                        f"Low assertion-to-logic ratio: "
                        f"{visitor.assertion_count}/{visitor.statement_count} statements "
                        f"are assertions"
                    ),
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Test has too much setup/logic relative to assertions",
                )
            )

        # Check for excessive @pytest.mark.parametrize combinations
        self._check_excessive_parametrize(test, result)

        # Store metadata
        result.metadata["statement_count"] = visitor.statement_count
        result.metadata["assertion_count"] = visitor.assertion_count
        result.metadata["max_depth"] = visitor.max_depth
        result.metadata["cyclomatic_complexity"] = visitor.cyclomatic_complexity

    @staticmethod
    def _check_excessive_parametrize(test: TestItemInfo, result: AnalyzerResult) -> None:
        """Check for @pytest.mark.parametrize with too many cases."""
        for decorator in test.node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            if call is None:
                continue
            # Match pytest.mark.parametrize(...)
            func = call.func
            is_parametrize = False
            if isinstance(func, ast.Attribute) and func.attr == "parametrize":
                is_parametrize = True
            if not is_parametrize:
                continue
            # Second positional arg is the parameter list
            if len(call.args) < 2:
                continue
            params_arg = call.args[1]
            case_count = 0
            if isinstance(params_arg, (ast.List, ast.Tuple)):
                case_count = len(params_arg.elts)
            if case_count > 20:
                result.add_issue(
                    Issue(
                        rule="complexity.excessive_parametrize",
                        message=(f"@pytest.mark.parametrize has {case_count} cases"),
                        severity=Severity.INFO,
                        file_path=test.file_path,
                        line=decorator.lineno,
                        test_name=test.name,
                        suggestion=(
                            "Consider splitting into focused test groups "
                            "or loading test data from a file"
                        ),
                    )
                )
