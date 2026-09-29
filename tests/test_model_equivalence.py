from dataclasses import fields, replace
from itertools import product

import pytest

pyo = pytest.importorskip("pyomo.environ")
from examples.supply_chain import SupplyData, build_model, sample_data  # noqa: E402

from .reference_models import (  # noqa: E402
    business_cost,
    business_feasible,
    constraint_rows,
    linear_terms,
    satisfies,
    signature,
    supply_model,
)

pytestmark = pytest.mark.integration


def tiny_data():
    prod = (("F1", "P1"), ("F2", "P1"))
    lanes = (("F1", "W1"),)
    store = (("W1", "P1"),)
    return SupplyData(
        prod,
        lanes,
        store,
        {"F1": 2, "F2": 2},
        dict.fromkeys(lanes, 2),
        dict.fromkeys(store, 2),
        dict.fromkeys(store, 2),
        dict.fromkeys(store, 1),
        dict.fromkeys(store, 0),
        dict.fromkeys(prod, 2),
        {"F1": 5, "F2": 5},
        {("F1", "W1", "P1"): 1},
        dict.fromkeys(store, 1),
    )


def transformed(data, variant):
    def label(key):
        if isinstance(key, tuple):
            return tuple(label(k) for k in key)
        return f"Label_{key}" if variant == "renamed" else key

    changes = {}
    for field in fields(data):
        value = getattr(data, field.name)
        if isinstance(value, dict):
            changes[field.name] = {label(k): v for k, v in reversed(tuple(value.items()))}
        else:
            changes[field.name] = tuple(label(k) for k in reversed(value))
    return replace(data, **changes)


@pytest.mark.parametrize("variant", ["original", "reversed", "renamed"])
def test_every_integer_assignment_against_business_rules(variant):
    data = tiny_data()
    if variant != "original":
        data = transformed(data, variant)
    composed, _ = build_model(data)
    handwritten = supply_model(data)
    assert signature(composed) == signature(handwritten)
    models = (composed, handwritten)
    rows = [constraint_rows(model) for model in models]
    variables = sorted(composed.component_data_objects(pyo.Var), key=lambda v: v.name)
    assignments = list(product(*(range(int(v.lb), int(v.ub) + 1) for v in variables)))
    assert len(assignments) == 972
    feasible_count = 0
    best = None
    objective_terms, constant = linear_terms(composed.objective.expr)
    for assignment in assignments:
        values = dict(zip((v.name for v in variables), assignment, strict=True))
        expected = business_feasible(data, composed, values)
        assert [satisfies(r, values) for r in rows] == [expected, expected]
        cost = business_cost(data, composed, values)
        assert sum(coef * values[name] for name, coef in objective_terms) + constant == cost
        if expected:
            feasible_count += 1
            best = cost if best is None else min(best, cost)
    assert feasible_count == 4
    assert best == 8


@pytest.mark.parametrize("scenario", ["normal", "unreachable", "stock"])
def test_full_sample_has_same_coefficients_bounds_integrality_and_objective(scenario):
    data = sample_data(scenario)
    composed, _ = build_model(data)
    assert signature(composed) == signature(supply_model(data))
