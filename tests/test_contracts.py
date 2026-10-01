"""Contracts inherited from the supplied prototype, with its identified gaps covered."""

import subprocess
import sys
from dataclasses import FrozenInstanceError, replace

import pytest
from relindex import Relation

from reloom import BuildContext, ContractError, Indexed, Port, Quantity, plan_equal, sum_over

from .conftest import Opaque


def test_missing_and_extra_are_reported_together(context, targets):
    with pytest.raises(ContractError) as caught:
        Indexed(targets, {("F1", "P1"): 3, ("F3", "P1"): 4}, context)
    error = caught.value
    assert error.code == "key_coverage"
    assert error.details["missing"] == (("F2", "P1"),)
    assert error.details["extra"] == (("F3", "P1"),)
    with pytest.raises(TypeError):
        error.details["extra"] = ()


@pytest.mark.parametrize("key", [(True,), (1.0,), ("a", "b"), "a", (None,)])
def test_invalid_mapping_keys(context, key):
    with pytest.raises((TypeError, ValueError)):
        Indexed(Relation([(1,)], schema=("id",)), {key: 1}, context)


@pytest.mark.parametrize("key", [(True,), (1.0,), (), "1", (2,)])
def test_both_lookup_paths_reject_aliases(context, key):
    family = Indexed(Relation([(1,)], schema=("id",)), {(1,): 5}, context)
    for accessor in (family, family.values):
        with pytest.raises(KeyError):
            accessor[key]


def test_mapping_is_shallow_read_only_snapshot(context):
    native = Opaque()
    values = {("a",): native}
    family = Indexed(Relation(values, schema=("id",)), values, context)
    values[("a",)] = Opaque()
    assert family[("a",)] is native
    with pytest.raises(TypeError):
        family.values[("a",)] = Opaque()
    with pytest.raises(FrozenInstanceError):
        family.context = context
    with pytest.raises(FrozenInstanceError):
        context.model = object()


@pytest.mark.parametrize("value", [None, True, False, float("nan"), float("inf"), -float("inf")])
def test_values_are_delegated_to_adapter(context, value):
    with pytest.raises(ContractError) as caught:
        Indexed(Relation([(1,)], schema=("id",)), {(1,): value}, context)
    assert caught.value.details["key"] == (1,)


def test_value_validator_is_scoped_to_each_validation_pass(context, monkeypatch):
    passes = []
    validate = context.adapter.validate_value

    def factory(model):
        assert model is context.model
        values = []
        passes.append(values)

        def check(value):
            values.append(value)
            validate(model, value)

        return check

    monkeypatch.setattr(context.adapter, "value_validator", factory, raising=False)
    domain = Relation([(1,), (2,)], schema=("id",))
    family = Indexed(domain, {(1,): 10, (2,): 20}, context)
    family._validate()
    assert passes == [[10, 20], [10, 20]]
    assert passes[0] is not passes[1]


def test_legacy_adapter_without_validator_factory_is_rechecked(context, monkeypatch):
    assert not hasattr(context.adapter, "value_validator")
    calls = []
    original = context.adapter.validate_value

    def validate(model, value):
        assert model is context.model
        calls.append(value)
        original(model, value)

    monkeypatch.setattr(context.adapter, "validate_value", validate)
    domain = Relation([(1,), (2,)], schema=("id",))
    family = Indexed(domain, {(1,): 10, (2,): 20}, context)
    family._validate()
    assert calls == [10, 20, 10, 20]
    with pytest.raises(ContractError) as caught:
        Indexed(domain, {(1,): 10, (2,): None}, context)
    assert calls == [10, 20, 10, 20, 10, None]
    assert caught.value.details["key"] == (2,)


def test_empty_family_rechecks_model_without_validating_values(context, monkeypatch):
    family = Indexed(Relation([], schema=("id",)), {}, context)

    def reject_model(model):
        raise ContractError("context", "model changed")

    def reject_value(model, value):
        raise AssertionError("empty family has no values")

    monkeypatch.setattr(context.adapter, "validate_value", reject_value)
    family._validate()
    monkeypatch.setattr(context.adapter, "validate_model", reject_model)
    with pytest.raises(ContractError, match="model changed"):
        family._validate()


def test_grouped_sum_retains_empty_key(context, source, targets):
    family = Indexed(source, {("F1", "W1", "P1"): 3, ("F1", "W2", "P1"): 4}, context)
    result = sum_over(family, "factory", "product", over=targets, empty="zero")
    assert dict(result.values) == {("F1", "P1"): 7, ("F2", "P1"): 0}
    assert result.context is context
    assert context.adapter.sums == [(3, 4), ()]


def test_empty_error_precedes_any_sum(context, source, targets):
    family = Indexed(source, dict.fromkeys(source.tuples(), 1), context)
    with pytest.raises(ContractError, match="Empty source groups") as caught:
        sum_over(family, "factory", "product", over=targets, empty="error")
    assert caught.value.details["keys"] == (("F2", "P1"),)
    assert context.adapter.sums == []


def test_outside_group_domain_is_not_silently_dropped(context, source):
    family = Indexed(source, dict.fromkeys(source.tuples(), 1), context)
    with pytest.raises(ValueError, match="outside the declared domain"):
        sum_over(
            family,
            "factory",
            "product",
            over=Relation([], schema=("factory", "product")),
            empty="zero",
        )


def test_group_policy_and_domain_are_explicit(context, source, targets):
    family = Indexed(source, dict.fromkeys(source.tuples(), 1), context)
    with pytest.raises(TypeError):
        sum_over(family, "factory", "product", over=targets)
    with pytest.raises(TypeError):
        sum_over(family, "factory", "product", empty="zero")
    with pytest.raises(ContractError):
        sum_over(family, "factory", "product", over=targets, empty="ignore")
    with pytest.raises(ValueError, match="At least one"):
        sum_over(family, over=Relation([()], schema=()), empty="zero")


def test_sum_uses_full_keys_including_period(context):
    domain = Relation([("a", "t", 1), ("a", "t", 2)], schema=("worker", "task", "period"))
    tasks = Relation([("t",)], schema=("task",))
    family = Indexed(domain, {("a", "t", 1): 7, ("a", "t", 2): 7}, context)
    assert domain.to_mapping(key="task", value="worker", over=tasks) == {"t": ("a",)}
    result = sum_over(family, "task", over=tasks, empty="error")
    assert result[("t",)] == 14
    assert context.adapter.sums == [(7, 7)]


def test_relational_projection_is_not_expression_aggregation(source):
    labels = Relation([("W1", "a"), ("W1", "b"), ("W2", "a")], schema=("warehouse", "tag"))
    joined = source.join(labels, on=("warehouse",))
    assert len(joined) == 3
    assert joined.project(*source.schema) == source


def test_rename_and_reorder_preserve_value_identity(context, targets):
    values = {key: Opaque() for key in targets.tuples()}
    family = Indexed(targets, values, context)
    renamed = family.rename({"factory": "site"})
    reordered = renamed.reorder("product", "site")
    assert reordered.domain.schema == ("product", "site")
    assert reordered[("P1", "F2")] is values[("F2", "P1")]
    assert reordered.context is context
    for columns in [("factory",), ("factory", "factory"), ("product", "unknown")]:
        with pytest.raises(ContractError):
            family.reorder(*columns)


def test_native_values_are_never_compared_in_core(context, targets):
    a = Indexed(targets, {key: Opaque() for key in targets.tuples()}, context)
    b = Indexed(targets, {key: Opaque() for key in targets.tuples()}, context)
    q = Quantity("shipment", "item", "period")
    left, right = Port("production", a, q), Port("shipping", b, q)
    plan = plan_equal(left, right, name="flow")
    assert plan.rows[0].lhs is a[("F1", "P1")]
    assert plan.rows[1].rhs is b[("F2", "P1")]
    assert left != right
    assert a != b
    assert plan != plan_equal(left, right, name="flow")


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "inventory"),
        ("unit", "case"),
        ("time_basis", "arrival-day"),
    ],
)
def test_quantity_mismatch(context, targets, field, value):
    family = Indexed(targets, dict.fromkeys(targets.tuples(), 0), context)
    q = Quantity("shipment", "item", "shipping-day")
    with pytest.raises(ContractError) as caught:
        plan_equal(
            Port("left", family, q),
            Port("right", family, replace(q, **{field: value})),
            name="flow",
        )
    assert caught.value.code == "quantity"
    assert caught.value.details["left_port"] == "left"


@pytest.mark.parametrize("value", ["", " ", None, 1, True])
def test_names_and_quantity_fields_are_nonempty_strings(context, targets, value):
    family = Indexed(targets, dict.fromkeys(targets.tuples(), 0), context)
    q = Quantity("shipment", "item", "period")
    with pytest.raises(ContractError):
        Port(value, family, q)
    for field in ("kind", "unit", "time_basis"):
        with pytest.raises(ContractError):
            replace(q, **{field: value})


def test_context_identity_even_for_same_model(context, targets):
    q = Quantity("shipment", "item", "period")
    a = Indexed(targets, dict.fromkeys(targets.tuples(), 0), context)
    b = Indexed(targets, a.values, BuildContext(context.model, context.adapter))
    with pytest.raises(ContractError, match="same BuildContext"):
        plan_equal(Port("left", a, q), Port("right", b, q), name="flow")


def test_connection_coverage_diagnostics(context, targets):
    q = Quantity("shipment", "item", "period")
    small = Relation([("F1", "P1")], schema=targets.schema)
    a = Indexed(targets, dict.fromkeys(targets.tuples(), 0), context)
    b = Indexed(small, dict.fromkeys(small.tuples(), 0), context)
    with pytest.raises(ContractError, match="left_only=.*F2") as caught:
        plan_equal(Port("left", a, q), Port("right", b, q), name="flow")
    assert caught.value.details["right_only"] == ()


def test_empty_schemas_still_checked(context):
    q = Quantity("shipment", "item", "period")
    a = Indexed(Relation([], schema=("factory", "product")), {}, context)
    b = Indexed(Relation([], schema=("product", "factory")), {}, context)
    with pytest.raises(ContractError) as caught:
        plan_equal(Port("left", a, q), Port("right", b, q), name="flow")
    assert caught.value.code == "schema"


def test_scalar_port_and_deterministic_key_order(context):
    domain = Relation([()], schema=())
    q = Quantity("cost", "JPY", "horizon")
    a = Port("left", Indexed(domain, {(): 10}, context), q)
    b = Port("right", Indexed(domain, {(): 20}, context), q)
    plan = plan_equal(a, b, name="cost")
    assert [(row.key, row.lhs, row.rhs) for row in plan.rows] == [((), 10, 20)]
    mixed = Relation([("a",), (3,), (1,)], schema=("id",))
    assert tuple(Indexed(mixed, dict.fromkeys(reversed(mixed.tuples()), 0), context).values) == (
        (1,),
        (3,),
        ("a",),
    )


def test_core_import_does_not_load_optional_dependencies():
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            """
import importlib.abc
import sys
class RejectOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pyomo', 'pulp', 'highspy', 'numpy'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, RejectOptional())
import reloom
""",
        ],
        check=True,
    )
