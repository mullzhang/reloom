"""Measure construction overhead against relindex and indexed handwritten Python."""

import argparse
import gc
import json
import platform
import statistics
import time
import tracemalloc
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pyomo.environ as pyo
from relindex import Relation

from reloom import Assembly, BuildContext, Indexed, Port, Quantity, plan_equal, sum_over
from reloom.adapters.pyomo import PyomoAdapter

MODES = ("reloom", "relindex", "indexed_python")
STAGES = ("index", "native_model", "aggregate", "plan", "apply", "total")


def build(mode, size, fanout):
    start = time.perf_counter()
    rows = tuple((node, arc) for node in range(size) for arc in range(fanout))
    targets = tuple((node,) for node in range(size + 1))  # One isolated target.
    if mode == "indexed_python":
        groups = defaultdict(list, {key: [] for key in targets})
        for row in rows:
            groups[(row[0],)].append(row)
    else:
        domain = Relation(rows, schema=("node", "arc"))
        target = Relation(targets, schema=("node",))
        rows, targets = domain.tuples(), target.tuples()
        if mode == "relindex":
            groups = domain.group_by("node", over=target)
    index_end = time.perf_counter()

    model = pyo.ConcreteModel()
    model.arc_set = pyo.Set(dimen=2, initialize=rows)
    model.nodes = pyo.Set(dimen=1, initialize=(k[0] for k in targets))
    model.x = pyo.Var(model.arc_set, domain=pyo.NonNegativeReals, bounds=(0, 2))
    model.q = pyo.Var(model.nodes, bounds=lambda m, n: (0, 0) if n == size else (1, 1))
    model.objective = pyo.Objective(
        expr=pyo.quicksum((arc + 1) * model.x[n, arc] for n, arc in rows)
    )
    native_end = time.perf_counter()

    if mode == "reloom":
        context = BuildContext(model, PyomoAdapter())
        source = Indexed(domain, {k: model.x[k] for k in rows}, context)
        aggregated = sum_over(source, "node", over=target, empty="zero")
    else:
        aggregated = {key: pyo.quicksum(model.x[k] for k in group) for key, group in groups.items()}
    aggregate_end = time.perf_counter()

    if mode == "reloom":
        quantity = Quantity("flow", "unit", "period")
        lhs = Port("outgoing", aggregated, quantity)
        rhs = Port(
            "required", Indexed(target, {k: model.q[k[0]] for k in targets}, context), quantity
        )
        assembly = Assembly(context, name="connections")
        assembly.register(lhs, required=True)
        assembly.register(rhs, required=True)
        assembly.add(plan_equal(lhs, rhs, name="balance"))
    plan_end = time.perf_counter()

    if mode == "reloom":
        report = assembly.apply()
        assert report.constraint_count == size + 1
    else:
        model.connections = pyo.Block()
        model.connections.balance = pyo.ConstraintList()
        for key in targets:
            model.connections.balance.add(model.q[key[0]] == aggregated[key])
    end = time.perf_counter()
    times = (
        index_end - start,
        native_end - index_end,
        aggregate_end - native_end,
        plan_end - aggregate_end,
        end - plan_end,
        end - start,
    )
    return model, dict(zip(STAGES, (seconds * 1000 for seconds in times), strict=True))


def run(sizes, fanout, repeats):
    cases = []
    for size in sizes:
        for mode in MODES:
            build(mode, size, fanout)  # One unmeasured warmup per mode and size.
        samples = {mode: [] for mode in MODES}
        for repeat in range(repeats):
            order = MODES[repeat % len(MODES) :] + MODES[: repeat % len(MODES)]
            for mode in order:
                gc.collect()
                _, timing = build(mode, size, fanout)
                samples[mode].append(timing)
        for mode in MODES:
            gc.collect()
            tracemalloc.start()
            model, _ = build(mode, size, fanout)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            solver = pyo.SolverFactory("highs")
            start = time.perf_counter()
            result = solver.solve(model)
            solve_ms = (time.perf_counter() - start) * 1000
            assert result.solver.termination_condition == pyo.TerminationCondition.optimal
            assert abs(pyo.value(model.objective) - size) < 1e-6
            cases.append(
                {
                    "mode": mode,
                    "nodes": size,
                    "source_keys": size * fanout,
                    "target_keys": size + 1,
                    "variables": size * fanout + size + 1,
                    "constraints": size + 1,
                    "samples_ms": samples[mode],
                    "median_ms": {
                        stage: statistics.median(s[stage] for s in samples[mode])
                        for stage in STAGES
                    },
                    "python_peak_bytes": peak,
                    "solve_ms_single_run": solve_ms,
                    "objective": pyo.value(model.objective),
                }
            )
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {name: version(name) for name in ("reloom", "relindex", "pyomo", "highspy")},
        "repeats": repeats,
        "warmups_per_case": 1,
        "fanout": fanout,
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 5000])
    parser.add_argument("--fanout", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(*args.sizes, args.fanout, args.repeats) < 1:
        parser.error("sizes, fanout, and repeats must be positive")
    result = run(args.sizes, args.fanout, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for case in result["cases"]:
        print(
            f"{case['mode']:15} {case['source_keys']:6} source keys: "
            f"{case['median_ms']['total']:.2f} ms median, "
            f"{case['python_peak_bytes'] / 1024**2:.2f} MiB Python peak"
        )


if __name__ == "__main__":
    main()
