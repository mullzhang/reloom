# reloom

Connect optimization model components through explicit, validated interfaces.

reloom is a Python library for composing components such as production, shipping, and inventory into a shared optimization model.
Each component exposes indexed variables or expressions through a **port**. reloom checks that connected ports agree on their keys, quantity meanings, units, and time bases, then creates the equality constraints that connect them.

It builds on [relindex](https://github.com/mullzhang/relindex) for sparse index domains and [Pyomo](https://www.pyomo.org/) for optimization expressions and constraints.
You define each component's variables, internal constraints, and objective terms in ordinary Pyomo code.

## Getting started

Requires Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the root of a checkout of this repository, install reloom and the dependencies needed to run the examples:

```sh
uv sync --locked --extra pyomo --group solver
```

The core package depends on relindex. Pyomo is an optional extra; the examples also use the HiGHS solver.
See [Contributing](CONTRIBUTING.md) for development setup and checks.

## Connect production and shipping

Suppose factory F1 can ship to two warehouses, while F2 has no shipping routes.
We want each factory's production to equal its total outbound shipments.

```python
import pyomo.environ as pyo
from relindex import Relation

from reloom import Assembly, BuildContext, Indexed, Port, Quantity, plan_equal, sum_over
from reloom.adapters.pyomo import PyomoAdapter

# Define valid index combinations; F2 intentionally has no shipping route.
factories = Relation([("F1",), ("F2",)], schema=("factory",))
routes = Relation([("F1", "W1"), ("F1", "W2")], schema=("factory", "warehouse"))

# Create production (q) and shipment (x) variables in one shared model.
model = pyo.ConcreteModel()
model.q = pyo.Var(["F1", "F2"], domain=pyo.NonNegativeReals)
model.x = pyo.Var(routes.tuples(), domain=pyo.NonNegativeReals)
context = BuildContext(model, PyomoAdapter())

# Associate each complete domain key with its existing Pyomo variable.
production = Indexed(factories, {(f,): model.q[f] for f in model.q}, context)
shipping = Indexed(routes, {k: model.x[k] for k in routes.tuples()}, context)

# Sum shipments by factory, keeping F2 as an explicit empty sum of zero.
outbound = sum_over(shipping, "factory", over=factories, empty="zero")

# Expose both sides with matching meaning, unit, and time basis.
quantity = Quantity("shipment", "item", "same-period")
output = Port("production.output", production, quantity)
dispatch = Port("shipping.outbound", outbound, quantity)

# Mark both ports as required so a missing connection is an error.
assembly = Assembly(context, name="connections")
assembly.register(output, required=True)
assembly.register(dispatch, required=True)

# Check matching keys and quantities, then plan one equality per factory.
assembly.add(plan_equal(output, dispatch, name="production_shipping"))

# Revalidate the assembly and attach the planned constraints to the model.
report = assembly.apply()
assert report.constraint_count == 2
```

The generated constraints are:

```text
q[F1] = x[F1,W1] + x[F1,W2]
q[F2] = 0
```

Passing the full factory domain as `over` keeps F2 in the model even though it has no shipments.
`empty="zero"` treats its empty sum as zero. Use `empty="error"` when every target must have a contribution.
The [supply chain example](examples/supply_chain.py) extends this pattern with capacities, demand, inventory, and costs.

## How the pieces fit together

| API | Role |
| --- | --- |
| `BuildContext` | Shares one model and adapter across connected components. |
| `Indexed` | Associates each key in a relindex domain with a variable, expression, or number. |
| `sum_over` | Aggregates expressions over an explicit target domain, retaining empty groups. |
| `Quantity` and `Port` | Declare an exposed quantity's meaning, unit, and time basis. |
| `plan_equal` | Checks matching schemas, keys, quantities, and contexts before planning equalities. |
| `Assembly` | Checks required and duplicate connections, adds constraints, and returns a report. |

Missing or extra keys, incompatible quantities, and references to another model raise errors before connection constraints are attached.
Required ports must be connected, and each port can participate in at most one connection.
The returned `BuildReport` maps connection names and domain keys to the generated constraints, including constant equalities that are always true or false.

## Run the examples

```sh
uv run --no-sync python examples/supply_chain.py
uv run --no-sync python examples/supply_chain.py --scenario unreachable
uv run --no-sync python examples/supply_chain.py --scenario stock
uv run --no-sync python examples/network.py
```

- [Supply chain](examples/supply_chain.py): an integer model of production, shipping, and inventory. The default case has an optimal objective of 26. The unreachable case is infeasible; the stock case meets demand from initial inventory and has an optimal objective of 14.
- [Network flow](examples/network.py): a minimum-cost flow model with an optimal objective of 9. An isolated node remains in the connection domain as a true constant equality.

## Supported models

The current adapter supports Pyomo `ConcreteModel` instances. Ports accept finite numbers and scalar affine expressions, including expressions with integer or binary variables, mutable parameters, and fixed variables.
Connected components must share the same `BuildContext` and root model.

Applications define quantity meanings and model any unit conversions or time shifts explicitly.
Connection checks validate these declarations; overall feasibility is determined by the optimization model and solver.
Objective construction and solving remain under application control. Automatic decomposition and distributed solving are outside the library's scope.

Contract validation adds construction overhead. The [benchmarks](docs/benchmarks.md) compare reloom with direct relindex usage and indexed handwritten Python, with measurement conditions and results.

## Documentation

- [API reference](docs/api.md): contracts, expression requirements, assembly lifecycle, and errors.
- [Validation record](docs/validation.md): test coverage, independent model comparisons, and solver results.
- [Contributing](CONTRIBUTING.md): development, documentation checks, and distribution verification.

Licensed under the [MIT License](LICENSE).
