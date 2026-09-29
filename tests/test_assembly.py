from dataclasses import replace

import pytest
from relindex import Relation

from reloom import AdapterError, Assembly, Indexed, Port, Quantity, plan_equal


def ports(context, *, empty=False):
    domain = Relation([] if empty else [(1,)], schema=("id",))
    family = Indexed(domain, dict.fromkeys(domain.tuples(), 1), context)
    quantity = Quantity("flow", "item", "period")
    return Port("a", family, quantity), Port("b", family, quantity)


def test_empty_plan_keeps_endpoints_and_counts_as_connected(context):
    a, b = ports(context, empty=True)
    plan = plan_equal(a, b, name="empty")
    assert plan.left is a and plan.right is b and plan.rows == ()
    assembly = Assembly(context, name="links")
    assembly.register(a, required=True)
    assembly.register(b, required=True)
    assembly.add(plan)
    assembly.validate()
    assert context.adapter.attachments == []
    report = assembly.apply()
    assert len(report.connections) == 1
    assert report.connections[0].left_port == "a"
    assert report.constraint_count == 0


def test_missing_required_is_repairable_and_optional_may_be_unconnected(context):
    a, b = ports(context)
    assembly = Assembly(context, name="links")
    assembly.register(a, required=True)
    assembly.register(replace(a, name="optional"), required=False)
    with pytest.raises(ValueError, match="unconnected"):
        assembly.apply()
    assert assembly.state == "building"
    assert context.adapter.attachments == []
    assembly.register(b, required=True)
    assembly.add(plan_equal(a, b, name="flow"))
    assert assembly.apply().constraint_count == 1


def test_add_is_atomic_and_checks_same_registered_instance(context):
    a, b = ports(context)
    assembly = Assembly(context, name="links")
    assembly.register(a, required=True)
    with pytest.raises(ValueError, match="Unregistered"):
        assembly.add(plan_equal(a, b, name="flow"))
    assembly.register(b, required=True)
    with pytest.raises(ValueError, match="Unregistered"):
        assembly.add(plan_equal(replace(a), b, name="flow"))
    assembly.add(plan_equal(a, b, name="flow"))
    assert assembly.apply().constraint_count == 1


def test_duplicate_port_plan_and_degree_rejected(context):
    a, b = ports(context)
    c = replace(b, name="c")
    assembly = Assembly(context, name="links")
    for port in (a, b, c):
        assembly.register(port, required=False)
    with pytest.raises(ValueError, match="Duplicate port"):
        assembly.register(replace(a), required=False)
    with pytest.raises(ValueError, match="itself"):
        plan_equal(a, a, name="self")
    assembly.add(plan_equal(a, b, name="flow"))
    with pytest.raises(ValueError, match="Duplicate connection"):
        assembly.add(plan_equal(a, b, name="flow"))
    with pytest.raises(ValueError, match="already connected"):
        assembly.add(plan_equal(a, c, name="other"))
    assert assembly.apply().constraint_count == 1


@pytest.mark.parametrize("name", ["", "a.b", "a-b", "1a", "_a", "\u540d\u524d", True])
def test_native_names_are_restricted(context, name):
    a, b = ports(context)
    with pytest.raises(ValueError):
        Assembly(context, name=name)
    with pytest.raises(ValueError):
        plan_equal(a, b, name=name)


def test_required_is_mandatory_and_boolean(context):
    a, _ = ports(context)
    assembly = Assembly(context, name="links")
    with pytest.raises(TypeError):
        assembly.register(a)
    with pytest.raises(ValueError):
        assembly.register(a, required=1)
    assembly.register(a, required=False)
    assembly.apply()


def test_successful_application_is_single_use(context):
    a, b = ports(context)
    assembly = Assembly(context, name="links")
    assembly.register(a, required=True)
    assembly.register(b, required=True)
    plan = plan_equal(a, b, name="flow")
    assembly.add(plan)
    assembly.apply()
    assert assembly.state == "applied"
    for action in (
        assembly.apply,
        assembly.validate,
        lambda: assembly.add(plan),
        lambda: assembly.register(a, required=False),
    ):
        with pytest.raises(ValueError, match="applied"):
            action()
    assert len(context.adapter.attachments) == 1


@pytest.mark.parametrize("stage", ["prepare", "attach"])
def test_native_failure_is_chained_and_not_retryable(context, monkeypatch, stage):
    def fail(*args):
        raise RuntimeError("backend failure")

    monkeypatch.setattr(context.adapter, stage, fail)
    assembly = Assembly(context, name="links")
    with pytest.raises(AdapterError) as caught:
        assembly.apply()
    assert caught.value.stage == stage
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert assembly.state == "failed"
    with pytest.raises(ValueError, match="failed"):
        assembly.apply()
