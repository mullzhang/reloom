# API reference

This document covers `reloom` 0.1.0. Import the common API from `reloom` and the Pyomo adapter from `reloom.adapters.pyomo`.
See the [README](../README.md) and [examples](../examples/supply_chain.py) for runnable code.

## Build context

```python
BuildContext(model, adapter)
```

An immutable declaration that pairs one model with an adapter.
Pass **the same context instance** to every component you intend to connect.
A different `BuildContext` wrapping the same model represents a separate build context.
The `model` and `adapter` references cannot be reassigned.
The adapter extension interface is internal in this initial release.

## Indexed values

```python
Indexed(domain, values, context)
```

| Argument | Description |
| --- | --- |
| `domain` | A `relindex.Relation` defining column names, column order, and existing keys. |
| `values` | A `Mapping` from tuple keys to native variables, expressions, or numbers. |
| `context` | The shared `BuildContext`. |

The key set must exactly match `domain`. Both missing and extra keys are reported.
Labels must be built-in `int` or `str` values, as in `relindex`. Even a single-column key must be a tuple such as `("F1",)`.
Boolean or floating-point labels and scalar string keys are rejected.
`family[key]` and `family.values[key]` apply the same checks: neither treats `(True,)` or `(1.0,)` as an alias for the integer key `(1,)`.
Looking up a missing key raises `KeyError`.

The mapping is shallow-copied during construction and exposed as read-only.
Later changes to the original dictionary have no effect, while each expression object retains its identity.
This does not prevent changes to expressions or updates to variable values.
Iteration follows `domain.tuples()`, independent of the input dictionary's order.

An empty domain retains its schema and context.
Represent a scalar quantity with `Relation([()], schema=())` and `{(): expression}`.

```python
renamed = family.rename({"factory": "site"})
reordered = renamed.reorder("product", "site")
```

`rename` changes column names; `reorder` changes the order of all columns.
Values move with their corresponding keys without being aggregated again.
`reorder` cannot drop or duplicate columns.
Use explicit aggregation, described below, for the many-to-one mapping that results from dropping columns.

## Aggregation

```python
sum_over(source, *columns, over=target_domain, empty="zero")
```

`columns` must contain at least one column. Both `over` and `empty` are required.
`over.schema` must match the names and order of the aggregation columns.
`relindex.group_by` groups complete source keys, and the context's adapter constructs the sums.
A source key whose group falls outside the declared target domain causes an error.

| `empty` | Target with no contributions |
| --- | --- |
| `"zero"` | Retain an empty sum. In Pyomo, this is the integer `0`. |
| `"error"` | Detect all empty groups and raise an error before aggregating expressions. |

If the same expression object is assigned to two different source keys, it contributes twice to the sum.
`to_mapping()` can drop columns such as periods and remove duplicates; it is not used to aggregate expressions.

## Ports and quantities

```python
Quantity(kind="shipment", unit="item", time_basis="same-period")
Port(name="production.output", family=family, quantity=quantity)
```

The three strings in `Quantity` declare meaning, unit, and time basis.
Empty strings and whitespace-only strings are rejected. Other strings are compared exactly, without normalization.
`Port.name` must also be a built-in string containing at least one non-whitespace character.
The fields of `Port` and `Quantity` cannot be reassigned after construction.

The two port names may differ.
These contracts check consistency between declared quantities. Unit conversion and the business correctness of the declarations remain the application's responsibility.

## Connection plans

```python
plan = plan_equal(left, right, name="production_shipping")
```

Returns an `EqualityPlan` without modifying the model.
It checks context identity, column names and order, key sets, the three quantity attributes, and expression validity.
Connecting a port to itself is rejected.
Column order and units are not corrected automatically, and connections are not silently restricted to common keys.

Inspect a plan through `plan.name`, `plan.left`, `plan.right`, and `plan.rows`.
Each `Equality` row holds `key`, `lhs`, and `rhs`. The common layer does not compare expressions for equality or evaluate their truth values.
Both ports remain in the plan even when the domain is empty.

## Assembly

```python
assembly = Assembly(context, name="connections")
assembly.register(left, required=True)
assembly.register(right, required=True)
assembly.add(plan)
assembly.validate()
report = assembly.apply()
```

The `required` argument to `register` is a mandatory `bool`.
A plan passed to `add` must use **the exact port instances** already registered.
Port names and connection names must each be unique within the registry, and each port may have at most one connection.
A port registered with `required=False` may remain unconnected.
An empty plan still counts as a connection for both endpoint ports.

Assembly and connection names must match `[A-Za-z][A-Za-z0-9_]*`.
An assembly name that collides with an existing model attribute is rejected before anything is attached.
Register all ports you want to validate together in one `Assembly`.
Validation covers that assembly's registry.

`validate()` checks for unconnected required ports and validates every expression without modifying the model.
`apply()` revalidates, prepares all constraints in a detached Pyomo Block, and then attaches the block to the model once.
After a prevalidation error, you can correct the registration state and retry.
An unexpected failure during native preparation or attachment sets `state="failed"` and prevents retrying.
Rebuild the model in that case. Rollback is not guaranteed for arbitrary backend failures.

A successful application sets `state="applied"`. Further registration, connection additions, validation, and application are rejected.
Changes to expressions or model structure after application are not tracked.

## Build results

`BuildReport` has an immutable structure and retains references to native constraints.

| Attribute | Description |
| --- | --- |
| `name` | Assembly name. |
| `connections` | A tuple of `ConnectionReport` objects, sorted by connection name. |
| `constraint_count` | Total number of generated constraints. |
| `constant_true_count` | Number of constant constraints evaluated as true. |
| `constant_false_count` | Number of constant constraints evaluated as false. |

Each `ConnectionReport` holds `name`, `left_port`, `right_port`, and `rows`.
Each `ConstraintRecord` holds the domain `key`, the classification `kind`, and the Pyomo `constraint`.
`kind` is one of `"symbolic"`, `"constant_true"`, or `"constant_false"`.
Constant equalities use no implicit tolerance.
`0.1 + 0.2 = 0.3` is classified as false because the Python floating-point values differ.
If a requirement needs a tolerance, express it as ordinary model constraints.

## Pyomo adapter

`PyomoAdapter()` accepts a constructed `ConcreteModel`.
Ports may expose variables, parameters, and named expressions in Blocks under the same root model.
The adapter rejects:

- `None`, `bool`, strings, complex numbers, `NaN`, and infinity.
- Entire indexed variable components, constraints, and relational expressions.
- References retained in the expression tree to another model's variables, fixed variables, parameters, or named expressions.
- Public expressions that are not affine in the variables, such as variable products or division by a variable.

Constant terms are checked at their current values, so parameters must be initialized.
Fixed variables are still treated as variables when checking linearity.
For example, the adapter rejects the product of a fixed `x` and an unfixed `y`, which would become nonlinear if `x` were later unfixed.
Mutable parameters may serve as linear coefficients or constant terms, and connection constraints retain references to them.

The adapter cannot recover the origin of immutable parameters that Pyomo has already replaced with numbers, or references already removed from the expression tree.
It checks the references retained in the supplied expression.
All expression nodes are traversed before simplification, including retained references to fixed variables and terms with zero coefficients.

## Errors

`ContractError` derives from `ValueError` and exposes a classification `code` and read-only `details`.

| `code` | Typical cause |
| --- | --- |
| `name` | An empty identifier or an invalid connection name. |
| `key_coverage` | Missing or extra indexed keys or connection targets. |
| `schema` | Mismatched column names or order, or an invalid reordering. |
| `empty_group` | Empty groups or an unsupported empty-group policy. |
| `quantity` | Mismatched meanings, units, or time bases. |
| `context` | A different context or an invalid model. |
| `expression` | A nonfinite value, an expression from another model, or a nonlinear expression. |
| `connection` | A connection from a port to itself. |
| `assembly` | Unconnected or unregistered ports, duplicates, name collisions, or an already applied assembly. |

Depending on the cause, `details` may contain keys, schemas, port names, or connection names.
Full set differences are retained in `details`; messages show the count and at most the first five entries.
Invalid key types or `Relation` operations propagate the underlying `relindex` `TypeError` or `ValueError`.

`AdapterError` represents an unexpected failure in native operations.
It retains `assembly`, `stage` (`"prepare"` or `"attach"`), and the original exception as `__cause__`.
Solver termination states are not converted into these exceptions; applications read them from Pyomo.
