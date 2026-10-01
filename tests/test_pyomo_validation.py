"""Validation-pass reuse must never cache values or model ownership."""

import math

import pytest
from relindex import Relation

from reloom import (
    Assembly,
    BuildContext,
    ContractError,
    Indexed,
    Port,
    Quantity,
    plan_equal,
    sum_over,
)

pyo = pytest.importorskip("pyomo.environ")
from reloom.adapters import pyomo as backend  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def model():
    model = pyo.ConcreteModel()
    model.x = pyo.Var()
    model.y = pyo.Var()
    model.p = pyo.Param(initialize=2, mutable=True)
    model.e = pyo.Expression(expr=model.x / model.p)
    return model


def test_one_walker_per_validation_pass_and_every_value_is_walked(model, monkeypatch):
    walkers = []
    visits = []
    original = backend.StreamBasedExpressionVisitor

    def make_walker(**kwargs):
        walker = original(**kwargs)
        walk = walker.walk_expression

        def record(value):
            visits.append(value)
            return walk(value)

        walker.walk_expression = record
        walkers.append(walker)
        return walker

    monkeypatch.setattr(backend, "StreamBasedExpressionVisitor", make_walker)
    domain = Relation([(0,), (1,), (2,)], schema=("id",))
    family = Indexed(
        domain, dict.fromkeys(domain.tuples(), model.e), BuildContext(model, backend.PyomoAdapter())
    )
    assert len(walkers) == 1
    assert len(visits) == 3 and all(value is model.e for value in visits)
    family._validate()
    family.rename({"id": "item"})
    assert len(walkers) == 3
    assert len({id(walker) for walker in walkers}) == 3
    assert len(visits) == 9 and all(value is model.e for value in visits)


def test_deep_and_heterogeneous_values_do_not_leak_traversal_state(model, monkeypatch):
    fallbacks = []
    original = backend.StreamBasedExpressionVisitor._nonrecursive_walker_loop

    def nonrecursive(walker, *args):
        fallbacks.append(walker)
        return original(walker, *args)

    monkeypatch.setattr(
        backend.StreamBasedExpressionVisitor, "_nonrecursive_walker_loop", nonrecursive
    )
    model.deep = pyo.Expression(range(1200))
    expression = model.x
    for index in model.deep:
        model.deep[index].set_value(expression)
        expression = model.deep[index]
    values = [expression, 0, model.p, model.y, model.e, 3 * model.x - model.y, -2.5]
    domain = Relation([(index,) for index in range(len(values))], schema=("id",))
    family = Indexed(
        domain,
        dict(zip(domain.tuples(), values, strict=True)),
        BuildContext(model, backend.PyomoAdapter()),
    )
    assert fallbacks
    family._validate()
    model.deep[0].set_value(model.x * model.y)
    with pytest.raises(ContractError, match="affine") as caught:
        family._validate()
    assert caught.value.details["key"] == (0,)
    model.deep[0].set_value(model.x)
    family._validate()


@pytest.mark.parametrize(
    "operation", ["rename", "reorder", "sum_over", "plan_equal", "add", "validate", "apply"]
)
@pytest.mark.parametrize("mutation", ["nonlinear", "foreign", "nonfinite", "zero"])
def test_public_operations_recheck_mutations_and_recover(model, operation, mutation):
    context = BuildContext(model, backend.PyomoAdapter())
    domain = Relation([(0,), (1,)], schema=("id",))
    family = Indexed(domain, {(0,): model.x, (1,): model.e}, context)
    quantity = Quantity("flow", "item", "period")
    left = Port("left", family, quantity)
    right = Port("right", Indexed(domain, {(0,): 0, (1,): 0}, context), quantity)
    plan = plan_equal(left, right, name="flow")
    build = Assembly(context, name="links")
    build.register(left, required=True)
    build.register(right, required=True)
    if operation != "add":
        build.add(plan)
    actions = {
        "rename": lambda: family.rename({"id": "item"}),
        "reorder": lambda: family.reorder("id"),
        "sum_over": lambda: sum_over(family, "id", over=domain, empty="error"),
        "plan_equal": lambda: plan_equal(left, right, name="flow"),
        "add": lambda: build.add(plan),
        "validate": build.validate,
        "apply": build.apply,
    }
    if mutation == "nonlinear":
        model.e.set_value(model.x * model.y)
    elif mutation == "foreign":
        foreign = pyo.ConcreteModel()
        foreign.x = pyo.Var()
        model.e.set_value(foreign.x)
    else:
        model.p.set_value(math.inf if mutation == "nonfinite" else 0)

    before = tuple(model.component_map())
    with pytest.raises(ContractError) as caught:
        actions[operation]()
    assert caught.value.code == "expression"
    assert caught.value.details["key"] == (1,)
    assert caught.value.details["schema"] == (("item",) if operation == "rename" else ("id",))
    assert tuple(model.component_map()) == before
    assert build.state == "building"

    model.p.set_value(2)
    model.e.set_value(model.x / model.p)
    actions[operation]()


def test_shared_adapter_keeps_each_validation_bound_to_its_model(model):
    adapter = backend.PyomoAdapter()
    foreign = pyo.ConcreteModel()
    foreign.x = pyo.Var()
    domain = Relation([(0,), (1,)], schema=("id",))
    first = Indexed(domain, {(0,): model.x, (1,): model.e}, BuildContext(model, adapter))
    second = Indexed(
        domain, dict.fromkeys(domain.tuples(), foreign.x), BuildContext(foreign, adapter)
    )
    first._validate()
    second._validate()
    model.e.set_value(foreign.x)
    with pytest.raises(ContractError, match="another model") as caught:
        first._validate()
    assert caught.value.details["key"] == (1,)
    second._validate()
    model.e.set_value(model.x)
    first._validate()


@pytest.mark.parametrize("override", ["subclass", "instance"])
def test_custom_per_value_validation_is_preserved(model, override):
    calls = []

    class CustomAdapter(backend.PyomoAdapter):
        def validate_value(self, owner, value):
            calls.append((owner, value))
            super().validate_value(owner, value)
            if value is model.y:
                raise ContractError("expression", "custom rejection")

    adapter = CustomAdapter()
    if override == "instance":
        custom = adapter.validate_value
        adapter = backend.PyomoAdapter()
        adapter.validate_value = custom
    context = BuildContext(model, adapter)
    domain = Relation([(0,), (1,)], schema=("id",))
    with pytest.raises(ContractError, match="custom rejection") as caught:
        Indexed(domain, {(0,): model.x, (1,): model.y}, context)
    assert caught.value.details["key"] == (1,)
    assert len(calls) == 2
    assert all(owner is model for owner, _ in calls)
    assert calls[0][1] is model.x and calls[1][1] is model.y


def test_direct_validation_rechecks_mutable_values(model):
    adapter = backend.PyomoAdapter()
    adapter.validate_value(model, model.e)
    model.p.set_value(0)
    with pytest.raises(ContractError, match="zero"):
        adapter.validate_value(model, model.e)
    model.p.set_value(2)
    adapter.validate_value(model, model.e)
