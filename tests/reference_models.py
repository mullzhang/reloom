"""Handwritten models. Intentionally no relindex/reloom or component builders."""

from collections import Counter

import pyomo.environ as pyo
from pyomo.repn import generate_standard_repn


def shipping_keys(data):
    return tuple(
        sorted(
            {
                (f, w, p)
                for f, p in data.production
                for origin, w in data.lanes
                if origin == f and (w, p) in data.storage
            }
        )
    )


def supply_model(data):
    m = pyo.ConcreteModel()
    m.production = pyo.Block()
    m.shipping = pyo.Block()
    m.inventory = pyo.Block()
    prod, ship, inv = m.production, m.shipping, m.inventory
    prod.key_set = pyo.Set(dimen=2, initialize=sorted(data.production))
    prod.q = pyo.Var(
        prod.key_set, domain=pyo.NonNegativeIntegers, bounds=lambda b, f, p: (0, data.capacity[f])
    )
    prod.y = pyo.Var(sorted(data.capacity), domain=pyo.Binary)
    prod.capacity = pyo.Constraint(
        sorted(data.capacity),
        rule=lambda b, f: (
            pyo.quicksum(b.q[a, p] for a, p in data.production if a == f)
            <= data.capacity[f] * b.y[f]
        ),
    )
    routes = shipping_keys(data)
    ship.key_set = pyo.Set(dimen=3, initialize=routes)
    ship.lanes = pyo.Set(dimen=2, initialize=sorted(data.lanes))
    ship.x = pyo.Var(
        ship.key_set,
        domain=pyo.NonNegativeIntegers,
        bounds=lambda b, f, w, p: (0, data.lane_capacity[(f, w)]),
    )
    ship.capacity = pyo.Constraint(
        ship.lanes,
        rule=lambda b, f, w: (
            None,
            pyo.quicksum(b.x[a, z, p] for a, z, p in routes if (a, z) == (f, w)),
            data.lane_capacity[(f, w)],
        ),
    )
    inv.key_set = pyo.Set(dimen=2, initialize=sorted(data.storage))
    inv.received = pyo.Var(
        inv.key_set,
        domain=pyo.NonNegativeIntegers,
        bounds=lambda b, w, p: (0, data.receipt_capacity[(w, p)]),
    )
    inv.stock = pyo.Var(
        inv.key_set,
        domain=pyo.NonNegativeIntegers,
        bounds=lambda b, w, p: (0, data.stock_capacity[(w, p)]),
    )
    inv.balance = pyo.Constraint(
        inv.key_set,
        rule=lambda b, w, p: (
            data.initial[(w, p)] + b.received[w, p] == data.demand[(w, p)] + b.stock[w, p]
        ),
    )
    m.production_shipping = pyo.Constraint(
        prod.key_set,
        rule=lambda m, f, p: (
            prod.q[f, p] == pyo.quicksum(ship.x[a, w, z] for a, w, z in routes if (a, z) == (f, p))
        ),
    )
    m.shipping_inventory = pyo.Constraint(
        inv.key_set,
        rule=lambda m, w, p: (
            pyo.quicksum(ship.x[f, a, z] for f, a, z in routes if (a, z) == (w, p))
            == inv.received[w, p]
        ),
    )
    m.objective = pyo.Objective(
        expr=(
            sum(data.production_cost[k] * prod.q[k] for k in data.production)
            + sum(data.startup_cost[f] * prod.y[f] for f in data.capacity)
            + sum(data.shipping_cost[k] * ship.x[k] for k in routes)
            + sum(data.holding_cost[k] * inv.stock[k] for k in data.storage)
        )
    )
    return m


def linear_terms(expression):
    repn = generate_standard_repn(expression)
    assert repn.is_linear()
    return tuple(
        sorted(
            (v.name, float(c))
            for v, c in zip(repn.linear_vars, repn.linear_coefs, strict=True)
            if c != 0
        )
    ), float(repn.constant)


def constraint_rows(model):
    rows = []
    for c in model.component_data_objects(pyo.Constraint, active=True):
        terms, constant = linear_terms(c.body)
        lower = None if c.lower is None else float(pyo.value(c.lower)) - constant
        upper = None if c.upper is None else float(pyo.value(c.upper)) - constant
        if terms and terms[0][1] < 0:
            terms = tuple((name, -coef) for name, coef in terms)
            lower, upper = None if upper is None else -upper, None if lower is None else -lower
        rows.append((terms, lower, upper))
    return rows


def signature(model):
    variables = {
        v.name: (v.lb, v.ub, v.is_integer(), v.is_binary())
        for v in model.component_data_objects(pyo.Var)
    }
    objectives = [
        (int(o.sense), linear_terms(o.expr))
        for o in model.component_data_objects(pyo.Objective, active=True)
    ]
    return variables, Counter(constraint_rows(model)), objectives


def satisfies(rows, values):
    for terms, lower, upper in rows:
        total = sum(coef * values[name] for name, coef in terms)
        if (lower is not None and total < lower) or (upper is not None and total > upper):
            return False
    return True


def business_feasible(data, model, values):
    """Independent business equations, including capacity, startup, and balances."""
    q = {k: values[model.production.q[k].name] for k in data.production}
    y = {f: values[model.production.y[f].name] for f in data.capacity}
    x = {k: values[model.shipping.x[k].name] for k in shipping_keys(data)}
    r = {k: values[model.inventory.received[k].name] for k in data.storage}
    s = {k: values[model.inventory.stock[k].name] for k in data.storage}
    for f in data.capacity:
        if (
            sum(amount for (factory, _), amount in q.items() if factory == f)
            > data.capacity[f] * y[f]
        ):
            return False
    for f, w in data.lanes:
        if (
            sum(amount for (a, b, _), amount in x.items() if (a, b) == (f, w))
            > data.lane_capacity[f, w]
        ):
            return False
    for f, p in data.production:
        if q[f, p] != sum(amount for (a, _, b), amount in x.items() if (a, b) == (f, p)):
            return False
    for w, p in data.storage:
        if r[w, p] != sum(amount for (_, a, b), amount in x.items() if (a, b) == (w, p)):
            return False
        if data.initial[w, p] + r[w, p] != data.demand[w, p] + s[w, p]:
            return False
    return True


def business_cost(data, model, values):
    return (
        sum(data.production_cost[k] * values[model.production.q[k].name] for k in data.production)
        + sum(data.startup_cost[f] * values[model.production.y[f].name] for f in data.capacity)
        + sum(data.shipping_cost[k] * values[model.shipping.x[k].name] for k in shipping_keys(data))
        + sum(data.holding_cost[k] * values[model.inventory.stock[k].name] for k in data.storage)
    )
