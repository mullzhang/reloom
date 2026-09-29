import math

import pytest
from relindex import Relation

from reloom import (
    AdapterError,
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
from reloom.adapters.pyomo import PyomoAdapter  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def model():
    m = pyo.ConcreteModel()
    m.x = pyo.Var(bounds=(0, 10))
    m.y = pyo.Var(bounds=(0, 10))
    m.p = pyo.Param(initialize=2, mutable=True)
    m.fixed = pyo.Var(initialize=2)
    m.fixed.fix()
    m.e = pyo.Expression(expr=m.x + m.y)
    m.block = pyo.Block()
    m.block.z = pyo.Var()
    return m


def family(model, value):
    return Indexed(Relation([()], schema=()), {(): value}, BuildContext(model, PyomoAdapter()))


def assembly(model, lhs, rhs, *, name="links"):
    context = BuildContext(model, PyomoAdapter())
    domain = Relation([(i,) for i in range(len(lhs))], schema=("id",))
    quantity = Quantity("flow", "item", "period")
    a = Port("left", Indexed(domain, {(i,): v for i, v in enumerate(lhs)}, context), quantity)
    b = Port("right", Indexed(domain, {(i,): v for i, v in enumerate(rhs)}, context), quantity)
    result = Assembly(context, name=name)
    result.register(a, required=True)
    result.register(b, required=True)
    result.add(plan_equal(a, b, name="flow"))
    return result


def test_valid_affine_expressions_and_nested_blocks(model):
    for expression in (
        1,
        -2.5,
        model.x,
        3 * model.x - model.y + 4,
        model.p * model.x,
        model.x / model.p,
        model.e,
        model.block.z,
        model.fixed,
        model.x**0,
        model.x**1,
    ):
        assert family(model, expression)[()] is expression


@pytest.mark.parametrize("value", [None, True, False, "0", math.nan, math.inf, -math.inf, 1j])
def test_invalid_values(model, value):
    with pytest.raises(ContractError) as caught:
        family(model, value)
    assert caught.value.code == "expression"
    assert caught.value.details["key"] == ()


def test_constraints_and_indexed_variables_are_not_scalar_values(model):
    model.c = pyo.Constraint(expr=model.x <= 2)
    model.indexed = pyo.Var([1, 2])
    for value in (model.c, model.x <= 2, model.indexed):
        with pytest.raises(ContractError):
            family(model, value)


def test_reject_unconstructed_abstract_and_nonroot_models(model):
    for target in (object(), pyo.AbstractModel(), model.block):
        with pytest.raises(ContractError):
            BuildContext(target, PyomoAdapter())


def test_foreign_variables_fixed_variables_parameters_and_named_expressions(model):
    foreign = pyo.ConcreteModel()
    foreign.x = pyo.Var(initialize=1)
    foreign.fixed = pyo.Var(initialize=1)
    foreign.fixed.fix()
    foreign.p = pyo.Param(initialize=2, mutable=True)
    foreign.e = pyo.Expression(expr=1)
    foreign.nested = pyo.Expression(expr=model.x)
    for expression in (
        foreign.x,
        foreign.fixed,
        model.x + foreign.fixed,
        foreign.p,
        foreign.p * model.x,
        foreign.e,
        foreign.nested,
    ):
        with pytest.raises(ContractError, match="another model") as caught:
            family(model, expression)
        assert "component" in caught.value.details


def test_zero_coefficient_does_not_skip_retained_foreign_references(model):
    foreign = pyo.ConcreteModel()
    foreign.x = pyo.Var()
    with pytest.raises(ContractError, match="another model"):
        family(model, 0 * foreign.x + model.x)


def test_affineness_ignores_fixed_status(model):
    for expression in (
        model.x**2,
        model.x * model.y,
        model.fixed * model.x,
        pyo.sin(model.fixed),
        model.x / model.fixed,
        model.x**model.p,
        pyo.Expr_if(IF=model.x >= 1, THEN=model.x, ELSE=model.y),
    ):
        with pytest.raises(ContractError):
            family(model, expression)


def test_uninitialized_nonfinite_and_zero_denominator(model):
    model.uninitialized = pyo.Param(mutable=True)
    for expression in (model.uninitialized, math.inf * model.x, math.nan + model.x):
        with pytest.raises(ContractError):
            family(model, expression)
    model.p.set_value(0)
    with pytest.raises(ContractError, match="zero"):
        family(model, model.x / model.p)


def test_constant_true_false_have_keys_and_are_not_dropped(model):
    build = assembly(model, [0, 0, 0.1 + 0.2], [0, 1, 0.3])
    build.validate()
    assert not hasattr(model, "links")
    report = build.apply()
    assert report.constraint_count == 3
    assert report.constant_true_count == 1
    assert report.constant_false_count == 2
    rows = report.connections[0].rows
    assert tuple(r.key for r in rows) == ((0,), (1,), (2,))
    assert rows[0].constraint.model() is model
    assert pyo.value(rows[0].constraint.body) <= pyo.value(rows[0].constraint.upper)
    assert pyo.value(rows[1].constraint.body) > pyo.value(rows[1].constraint.upper)


def test_fixed_vars_and_mutable_params_remain_symbolic_after_apply(model):
    model.fixed.set_value(2)
    report = assembly(model, [model.fixed, model.p], [model.x, 2]).apply()
    assert report.constant_true_count == 0 and report.constant_false_count == 0
    fixed_row, param_row = report.connections[0].rows
    model.x.set_value(2)
    model.fixed.unfix()
    model.fixed.set_value(4)
    assert pyo.value(fixed_row.constraint.body) == 2
    model.p.set_value(3)
    assert pyo.value(param_row.constraint.body) != pyo.value(param_row.constraint.lower)


def test_last_invalid_expression_leaves_model_unchanged(model):
    foreign = pyo.ConcreteModel()
    foreign.x = pyo.Var()
    build = assembly(model, [model.x, model.e], [model.y, 0])
    before = tuple(model.component_map())
    model.e.set_value(foreign.x)
    with pytest.raises(ContractError, match="another model") as caught:
        build.apply()
    assert tuple(model.component_map()) == before
    assert build.state == "building"
    assert caught.value.details["key"] == (1,)
    model.e.set_value(model.x)
    assert build.apply().constraint_count == 2


def test_nonfinite_parameter_is_rechecked_before_apply(model):
    build = assembly(model, [model.p * model.x], [model.y])
    model.p.set_value(math.inf)
    with pytest.raises(ContractError):
        build.apply()
    assert not hasattr(model, "links")


def test_native_prepare_failure_leaves_no_partial_block(model, monkeypatch):
    build = assembly(model, [model.x, model.y], [0, 0])
    before = tuple(model.component_map())
    original = pyo.ConstraintList.add
    calls = 0

    def fail_second(constraints, expression):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected native failure")
        return original(constraints, expression)

    monkeypatch.setattr(pyo.ConstraintList, "add", fail_second)
    with pytest.raises(AdapterError) as caught:
        build.apply()
    assert caught.value.stage == "prepare"
    assert tuple(model.component_map()) == before
    assert build.state == "failed"


@pytest.mark.parametrize("name", ["x", "pprint", "links"])
def test_name_collision_preserves_existing_components(model, name):
    if name == "links":
        model.links = "user attribute"
    before = getattr(model, name)
    build = assembly(model, [model.x], [model.y], name=name)
    with pytest.raises(ContractError, match="already has"):
        build.apply()
    if name == "pprint":
        assert getattr(model, name).__func__ is before.__func__
    else:
        assert getattr(model, name) is before


def test_deterministic_constraints_independent_of_mapping_order(model):
    context = BuildContext(model, PyomoAdapter())
    domain = Relation([("b",), (3,), (1,)], schema=("id",))
    q = Quantity("flow", "item", "period")
    a = Port("left", Indexed(domain, dict.fromkeys(reversed(domain.tuples()), model.x), context), q)
    b = Port("right", Indexed(domain, dict.fromkeys(domain.tuples(), model.y), context), q)
    build = Assembly(context, name="links")
    build.register(a, required=True)
    build.register(b, required=True)
    build.add(plan_equal(a, b, name="flow"))
    rows = build.apply().connections[0].rows
    assert tuple(r.key for r in rows) == ((1,), (3,), ("b",))
    assert [r.constraint.name for r in rows] == [f"links.connection_flow[{i}]" for i in (1, 2, 3)]


def test_empty_sum_is_zero_and_repeated_native_terms_count_twice(model):
    context = BuildContext(model, PyomoAdapter())
    domain = Relation([("a", 1), ("a", 2)], schema=("node", "period"))
    source = Indexed(domain, dict.fromkeys(domain.tuples(), model.x), context)
    result = sum_over(
        source, "node", over=Relation([("a",), ("b",)], schema=("node",)), empty="zero"
    )
    model.x.set_value(3)
    assert pyo.value(result[("a",)]) == 6
    assert result[("b",)] == 0
