"""Core tests deliberately do not import a modeling library."""

import math

import pytest
from relindex import Relation

from reloom import BuildContext, BuildReport, ConnectionReport, ConstraintRecord, ContractError
from reloom.context import _Prepared


class Opaque:
    """A native expression that the common layer must never evaluate."""

    def __eq__(self, other):
        raise AssertionError("symbolic equality evaluated")

    def __bool__(self):
        raise AssertionError("symbolic truth evaluated")

    def __hash__(self):
        raise AssertionError("symbolic hash evaluated")


class RecordingAdapter:
    def __init__(self):
        self.sums = []
        self.attachments = []

    def validate_model(self, model):
        pass

    def validate_value(self, model, value):
        if isinstance(value, Opaque):
            return
        if type(value) is int or (type(value) is float and math.isfinite(value)):
            return
        raise ContractError("expression", "invalid value")

    def sum_terms(self, terms):
        terms = tuple(terms)
        self.sums.append(terms)
        return sum(terms)

    def validate_target(self, model, name):
        pass

    def prepare(self, model, name, plans):
        report = BuildReport(
            name,
            tuple(
                ConnectionReport(
                    plan.name,
                    plan.left.name,
                    plan.right.name,
                    tuple(ConstraintRecord(row.key, "symbolic", object()) for row in plan.rows),
                )
                for plan in plans
            ),
        )
        return _Prepared(object(), report)

    def attach(self, model, name, prepared):
        self.attachments.append(prepared)


@pytest.fixture
def context():
    return BuildContext(object(), RecordingAdapter())


@pytest.fixture
def targets():
    return Relation([("F1", "P1"), ("F2", "P1")], schema=("factory", "product"))


@pytest.fixture
def source():
    return Relation(
        [("F1", "W1", "P1"), ("F1", "W2", "P1")],
        schema=("factory", "warehouse", "product"),
    )
