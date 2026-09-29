"""Production, transport, and inventory composed into one integer model.

Run after installing reloom[pyomo] and highspy:
    python examples/supply_chain.py --scenario normal
    python examples/supply_chain.py --scenario unreachable
    python examples/supply_chain.py --scenario stock
"""

import argparse
import json
from dataclasses import dataclass, replace
from typing import Any

import pyomo.environ as pyo
from relindex import Relation

from reloom import (
    Assembly,
    BuildContext,
    BuildReport,
    Indexed,
    Port,
    Quantity,
    plan_equal,
    sum_over,
)
from reloom.adapters.pyomo import PyomoAdapter

type Pair = tuple[str, str]
type Triple = tuple[str, str, str]


@dataclass(frozen=True)
class SupplyData:
    production: tuple[Pair, ...]
    lanes: tuple[Pair, ...]
    storage: tuple[Pair, ...]
    capacity: dict[str, int]
    lane_capacity: dict[Pair, int]
    receipt_capacity: dict[Pair, int]
    stock_capacity: dict[Pair, int]
    demand: dict[Pair, int]
    initial: dict[Pair, int]
    production_cost: dict[Pair, int]
    startup_cost: dict[str, int]
    shipping_cost: dict[Triple, int]
    holding_cost: dict[Pair, int]


def sample_data(scenario: str = "normal") -> SupplyData:
    prod = (("F1", "P1"), ("F2", "P1"))
    lanes = (("F1", "W1"), ("F1", "W2"))
    store = (("W1", "P1"), ("W2", "P1"))
    data = SupplyData(
        prod,
        lanes,
        store,
        {"F1": 8, "F2": 2},
        dict.fromkeys(lanes, 8),
        dict.fromkeys(store, 8),
        dict.fromkeys(store, 8),
        {("W1", "P1"): 3, ("W2", "P1"): 4},
        {("W1", "P1"): 0, ("W2", "P1"): 1},
        dict.fromkeys(prod, 2),
        {"F1": 5, "F2": 5},
        {("F1", "W1", "P1"): 1, ("F1", "W2", "P1"): 2},
        dict.fromkeys(store, 1),
    )
    if scenario == "normal":
        return data
    if scenario in ("unreachable", "stock"):
        return replace(
            data,
            lanes=(("F1", "W1"),),
            lane_capacity={("F1", "W1"): 8},
            shipping_cost={("F1", "W1", "P1"): 1},
            initial={("W1", "P1"): 0, ("W2", "P1"): 4 if scenario == "stock" else 0},
        )
    raise ValueError(f"Unknown scenario: {scenario}")


@dataclass(frozen=True)
class Indices:
    production: Relation
    lanes: Relation
    storage: Relation
    shipping: Relation

    @classmethod
    def from_data(cls, data: SupplyData):
        production = Relation(data.production, schema=("factory", "product"))
        lanes = Relation(data.lanes, schema=("factory", "warehouse"))
        storage = Relation(data.storage, schema=("warehouse", "product"))
        shipping = (
            production.join(lanes, on=("factory",))
            .join(
                storage,
                on=("warehouse", "product"),
            )
            .project("factory", "warehouse", "product")
        )
        return cls(production, lanes, storage, shipping)


@dataclass(frozen=True)
class Production:
    output: Port[Any]
    cost: Any


@dataclass(frozen=True)
class Shipping:
    outbound: Port[Any]
    inbound: Port[Any]
    cost: Any


@dataclass(frozen=True)
class Inventory:
    intake: Port[Any]
    cost: Any


FLOW = Quantity("shipment", "item", "same-period")


def build_production(context, data, indices):
    block = pyo.Block(concrete=True)
    context.model.production = block
    keys = indices.production.tuples()
    factories = tuple(sorted(data.capacity))
    block.key_set = pyo.Set(dimen=2, initialize=keys)
    block.q = pyo.Var(
        block.key_set, domain=pyo.NonNegativeIntegers, bounds=lambda b, f, p: (0, data.capacity[f])
    )
    block.y = pyo.Var(factories, domain=pyo.Binary)
    products = indices.production.group_by(
        "factory",
        over=Relation(((f,) for f in factories), schema=("factory",)),
    )
    block.capacity = pyo.Constraint(
        factories,
        rule=lambda b, f: (
            pyo.quicksum(b.q[key] for key in products[(f,)]) <= data.capacity[f] * b.y[f]
        ),
    )
    output = Indexed(indices.production, {k: block.q[k] for k in keys}, context)
    cost = pyo.quicksum(data.production_cost[k] * block.q[k] for k in keys)
    cost += pyo.quicksum(data.startup_cost[f] * block.y[f] for f in factories)
    return Production(Port("production.output", output, FLOW), cost)


def build_shipping(context, data, indices):
    block = pyo.Block(concrete=True)
    context.model.shipping = block
    keys = indices.shipping.tuples()
    block.key_set = pyo.Set(dimen=3, initialize=keys)
    block.lanes = pyo.Set(dimen=2, initialize=indices.lanes.tuples())
    block.x = pyo.Var(
        block.key_set,
        domain=pyo.NonNegativeIntegers,
        bounds=lambda b, f, w, p: (0, data.lane_capacity[(f, w)]),
    )
    by_lane = indices.shipping.group_by("factory", "warehouse", over=indices.lanes)
    # A tuple constraint also handles lanes with no compatible products.
    block.capacity = pyo.Constraint(
        block.lanes,
        rule=lambda b, f, w: (
            None,
            pyo.quicksum(b.x[k] for k in by_lane[(f, w)]),
            data.lane_capacity[(f, w)],
        ),
    )
    shipments = Indexed(indices.shipping, {k: block.x[k] for k in keys}, context)
    outbound = sum_over(shipments, "factory", "product", over=indices.production, empty="zero")
    inbound = sum_over(shipments, "warehouse", "product", over=indices.storage, empty="zero")
    return Shipping(
        Port("shipping.outbound", outbound, FLOW),
        Port("shipping.inbound", inbound, FLOW),
        pyo.quicksum(data.shipping_cost[k] * block.x[k] for k in keys),
    )


def build_inventory(context, data, indices):
    block = pyo.Block(concrete=True)
    context.model.inventory = block
    keys = indices.storage.tuples()
    block.key_set = pyo.Set(dimen=2, initialize=keys)
    block.received = pyo.Var(
        block.key_set,
        domain=pyo.NonNegativeIntegers,
        bounds=lambda b, w, p: (0, data.receipt_capacity[(w, p)]),
    )
    block.stock = pyo.Var(
        block.key_set,
        domain=pyo.NonNegativeIntegers,
        bounds=lambda b, w, p: (0, data.stock_capacity[(w, p)]),
    )
    block.balance = pyo.Constraint(
        block.key_set,
        rule=lambda b, w, p: (
            data.initial[(w, p)] + b.received[w, p] == data.demand[(w, p)] + b.stock[w, p]
        ),
    )
    intake = Indexed(indices.storage, {k: block.received[k] for k in keys}, context)
    return Inventory(
        Port("inventory.intake", intake, FLOW),
        pyo.quicksum(data.holding_cost[k] * block.stock[k] for k in keys),
    )


def build_model(data: SupplyData) -> tuple[Any, BuildReport]:
    model = pyo.ConcreteModel()
    context = BuildContext(model, PyomoAdapter())
    indices = Indices.from_data(data)
    production = build_production(context, data, indices)
    shipping = build_shipping(context, data, indices)
    inventory = build_inventory(context, data, indices)

    assembly = Assembly(context, name="connections")
    for port in (production.output, shipping.outbound, shipping.inbound, inventory.intake):
        assembly.register(port, required=True)
    assembly.add(plan_equal(production.output, shipping.outbound, name="production_shipping"))
    assembly.add(plan_equal(shipping.inbound, inventory.intake, name="shipping_inventory"))
    # Costs belong to the application: include each exactly once.
    model.objective = pyo.Objective(expr=production.cost + shipping.cost + inventory.cost)
    return model, assembly.apply()


def solve(model) -> str:
    solver = pyo.SolverFactory("highs")
    result = solver.solve(model, load_solutions=False)
    status = result.solver.termination_condition
    if status == pyo.TerminationCondition.optimal:
        model.solutions.load_from(result)
    return str(status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("normal", "unreachable", "stock"), default="normal")
    args = parser.parse_args()
    model, report = build_model(sample_data(args.scenario))
    status = solve(model)
    output = {
        "scenario": args.scenario,
        "termination": status,
        "connection_constraints": report.constraint_count,
    }
    if status == "optimal":
        output["objective"] = pyo.value(model.objective)
        output["production"] = {
            str(k): pyo.value(model.production.q[k]) for k in model.production.q
        }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
