"""Minimum-cost flow with an isolated node retained as a constant equality."""

import json

import pyomo.environ as pyo
from relindex import Relation

from reloom import Assembly, BuildContext, Indexed, Port, Quantity, plan_equal, sum_over
from reloom.adapters.pyomo import PyomoAdapter


def build_model():
    nodes = Relation([("S",), ("A",), ("T",), ("I",)], schema=("node",))
    arcs = Relation([("S", "A"), ("A", "T"), ("S", "T")], schema=("origin", "destination"))
    capacity = {("S", "A"): 3, ("A", "T"): 3, ("S", "T"): 2}
    cost = {("S", "A"): 1, ("A", "T"): 1, ("S", "T"): 3}
    supply = {("S",): 4, ("A",): 0, ("T",): -4, ("I",): 0}
    model = pyo.ConcreteModel()
    model.arcs = pyo.Set(dimen=2, initialize=arcs.tuples())
    model.x = pyo.Var(
        model.arcs, domain=pyo.NonNegativeReals, bounds=lambda m, a, b: (0, capacity[(a, b)])
    )
    context = BuildContext(model, PyomoAdapter())
    flow = Indexed(arcs, {k: model.x[k] for k in arcs.tuples()}, context)
    outgoing = sum_over(flow, "origin", over=nodes.rename({"node": "origin"}), empty="zero").rename(
        {"origin": "node"}
    )
    incoming = sum_over(
        flow, "destination", over=nodes.rename({"node": "destination"}), empty="zero"
    ).rename({"destination": "node"})
    net = Indexed(nodes, {k: outgoing[k] - incoming[k] for k in nodes.tuples()}, context)
    quantity = Quantity("net_supply", "unit", "period")
    balance = Port("network.net", net, quantity)
    boundary = Port("external.supply", Indexed(nodes, supply, context), quantity)
    assembly = Assembly(context, name="connections")
    assembly.register(balance, required=True)
    assembly.register(boundary, required=True)
    assembly.add(plan_equal(balance, boundary, name="balance"))
    model.objective = pyo.Objective(expr=pyo.quicksum(cost[k] * model.x[k] for k in arcs.tuples()))
    return model, assembly.apply()


def main():
    model, report = build_model()
    result = pyo.SolverFactory("highs").solve(model, load_solutions=False)
    status = result.solver.termination_condition
    output = {
        "termination": str(status),
        "connection_constraints": report.constraint_count,
        "constant_true": report.constant_true_count,
    }
    if status == pyo.TerminationCondition.optimal:
        model.solutions.load_from(result)
        output["objective"] = pyo.value(model.objective)
        output["flow"] = {str(k): pyo.value(model.x[k]) for k in model.x}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
