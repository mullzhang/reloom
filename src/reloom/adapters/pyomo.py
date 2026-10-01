"""Pyomo 6.10.1 adapter for scalar affine expressions in one ConcreteModel."""

import math
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, cast

import pyomo.environ as pyo
from pyomo.core.expr.numeric_expr import (
    DivisionExpression,
    NegationExpression,
    PowExpression,
    ProductExpression,
    SumExpression,
)
from pyomo.core.expr.numvalue import NumericValue
from pyomo.core.expr.relational_expr import EqualityExpression
from pyomo.core.expr.visitor import StreamBasedExpressionVisitor

from reloom.connections import EqualityPlan
from reloom.context import _Prepared
from reloom.errors import ContractError
from reloom.reports import BuildReport, ConnectionReport, ConstraintKind, ConstraintRecord


def _finite(value: Any) -> None:
    if type(value) is int:
        return
    if type(value) is float and math.isfinite(value):
        return
    raise ContractError("expression", "Expected a finite built-in int or float", value=value)


def _immutable(value: Any) -> bool:
    return type(value) in (int, float) or bool(value.is_constant())


class PyomoAdapter:
    """Validate references before simplification; prepare constraints off-model."""

    def validate_model(self, model: object) -> None:
        if not isinstance(model, pyo.ConcreteModel) or not model.is_constructed():
            raise ContractError("context", "Expected a constructed Pyomo ConcreteModel")

    def validate_value(self, model: object, value: Any) -> None:
        self._value_validator(model)(value)

    def value_validator(self, model: object) -> Callable[[Any], None]:
        # Keep custom per-value validation in subclasses and instance overrides.
        validate = self.validate_value
        if getattr(validate, "__func__", None) is not PyomoAdapter.validate_value:
            return partial(validate, model)
        return self._value_validator(model)

    def _value_validator(self, model: object) -> Callable[[Any], None]:
        """Create a fresh walker for one validation pass, without caching results."""

        # The walker checks named expressions as well as variables/parameters.
        # Its degree deliberately treats fixed variables as variables: unfixing
        # a variable must not turn an accepted affine expression into a product.
        def enter(node: Any) -> tuple[None, list[int]]:
            if type(node) in (int, float):
                _finite(node)
                return None, []
            if not isinstance(node, NumericValue) or not node.is_numeric_type():
                raise ContractError("expression", "Expected a scalar Pyomo numeric expression")
            if node.is_component_type():
                if node.model() is not model:
                    raise ContractError(
                        "expression", "Expression references another model", component=node.name
                    )
            return None, []

        def leave(node: Any, degrees: list[int]) -> int:
            if type(node) in (int, float):
                return 0
            if node.is_variable_type():
                return 1
            if not any(degrees):
                _finite(pyo.value(node))
                return 0
            if node.is_named_expression_type() or isinstance(
                node, (SumExpression, NegationExpression)
            ):
                return max(degrees)
            if isinstance(node, ProductExpression) and sum(degrees) <= 1:
                return sum(degrees)
            if isinstance(node, DivisionExpression) and degrees[1] == 0:
                if pyo.value(node.arg(1)) == 0:
                    raise ContractError("expression", "Division by zero in an affine expression")
                return degrees[0]
            if isinstance(node, PowExpression) and degrees[1] == 0:
                exponent = node.arg(1)
                if _immutable(exponent):
                    power = pyo.value(exponent)
                    if power == 0:
                        return 0
                    if power == 1:
                        return degrees[0]
            raise ContractError("expression", "Only affine expressions are supported")

        walker = StreamBasedExpressionVisitor(enterNode=enter, exitNode=leave)

        def validate(value: Any) -> None:
            try:
                walker.walk_expression(value)
            except ContractError:
                raise
            except (TypeError, ValueError, ArithmeticError) as error:
                raise ContractError("expression", f"Invalid numeric expression: {error}") from error

        return validate

    def sum_terms(self, terms: Iterable[Any]) -> Any:
        return pyo.quicksum(terms)

    def validate_target(self, model: object, name: str) -> None:
        if hasattr(model, name):
            raise ContractError(
                "assembly", f"Model already has an attribute named {name!r}", assembly=name
            )

    def prepare(self, model: object, name: str, plans: tuple[EqualityPlan[Any], ...]) -> _Prepared:
        block = pyo.Block(concrete=True)
        connections: list[ConnectionReport] = []
        for plan in plans:
            constraints = pyo.ConstraintList()
            block.add_component(f"connection_{plan.name}", constraints)
            records: list[ConstraintRecord] = []
            for row in plan.rows:
                kind: ConstraintKind = "symbolic"
                if _immutable(row.lhs) and _immutable(row.rhs):
                    equal = pyo.value(row.lhs) == pyo.value(row.rhs)
                    kind = "constant_true" if equal else "constant_false"
                    expression = pyo.Constraint.Feasible if equal else pyo.Constraint.Infeasible
                else:
                    # Do not let native Python scalars turn equality into bool.
                    expression = EqualityExpression((row.lhs, row.rhs))
                constraint = constraints.add(expression)
                records.append(ConstraintRecord(row.key, kind, constraint))
            connections.append(
                ConnectionReport(plan.name, plan.left.name, plan.right.name, tuple(records))
            )
        return _Prepared(block, BuildReport(name, tuple(connections)))

    def attach(self, model: object, name: str, prepared: _Prepared) -> None:
        cast(Any, model).add_component(name, prepared.native)
