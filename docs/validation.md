# Validation record

Validation date: 2026-09-29. This record covers the common contracts, Pyomo integration, examples, and distributions of `reloom` 0.1.0.
PuLP integration is deferred and is outside the completed scope.

## Environment

| Component | Verified version |
| --- | --- |
| OS | macOS 27.0, arm64 |
| Python | 3.12.13, 3.14.6 |
| relindex | 0.1.0, Git commit `7ef35a66d910b389ad38b2a197765388adf2e86a` |
| Pyomo | 6.10.1 |
| HiGHS | Python package `highspy` 1.15.1 |
| pytest | 9.1.1 |
| Ruff / mypy | 0.16.9 / 1.20.2 |

## Contracts and models

All 91 test cases passed on both Python 3.12.13 and 3.14.6.
Ruff lint and formatting checks and strict mypy checks also passed.
The tests cover four layers:

| Layer | Coverage |
| --- | --- |
| Common layer | Contracts from the supplied prototype, exact key coverage, empty groups, column transformations, quantities, contexts, missing connections, and repeated application. |
| Pyomo | Expression ownership and finiteness, fixed variables, mutable parameters, nonlinear expressions, constant constraints, revalidation before application, and absence of attached constraints after preparation failure. |
| Independent model comparison | Variable bounds and integrality, coefficients and bounds of every constraint, duplicate constraint counts, the objective, and every integer assignment. |
| Solving | Demand fulfillment, unreachable targets, initial inventory, minimum-cost flow, and infeasibility caused by a false constant constraint. |

All 972 assignments were enumerated for a small bounded integer model of production, shipping, and inventory.
An independent evaluation of the business equations, a handwritten model, and the `reloom` model agreed on the feasible set: four feasible assignments and an optimal objective of 8.
The same checks passed for all 972 assignments in each of two variants: reversed input order and consistently renamed labels.
The reference model and business equations do not use `plan_equal` or `sum_over`.

The examples produced the following results. Handwritten models also reproduced the termination states and optimal objectives for all three supply chain scenarios.

| Example | Termination | Optimal objective | Boundary checked |
| --- | --- | ---: | --- |
| Supply chain: normal | optimal | 26 | Production at F2, which has no route, is zero. |
| Supply chain: unreachable | infeasible | — | Demand at a warehouse with no route or stock is retained. |
| Supply chain: initial stock | optimal | 14 | Stock can meet demand without a shipping route. |
| Minimum-cost flow | optimal | 9 | The true constant constraint for an isolated node is retained. |

## Distributions and documentation

The [distribution verification script](../scripts/verify_wheel.py) compares a wheel built from the source tree with one rebuilt from the sdist.
It separately builds a wheel for the pinned `relindex` commit and tests the installed packages in fresh environments outside the repository.
The core-only environment was also checked for the absence of Pyomo, PuLP, HiGHS, and NumPy.
On both Python 3.12.13 and 3.14.6, the installed distributions passed 54 common-layer tests, all 91 tests with Pyomo installed, and four standalone example runs.
Both dependency retrieval paths were verified: reading a local Git repository and the default path of cloning from GitHub into a temporary directory.
The [documentation validation script](../scripts/check_docs.py) verified the README's Python example and the relative links and syntax of the six Markdown files present during the initial validation, then rendered them to HTML.

Obtaining packages through PyPI, running CI on GitHub, and publishing or releasing packages are separate from this local validation.
CI is configured, but no remote run results have been recorded yet.
See the [construction benchmark record](benchmarks.md) for performance measurements and their limits.

## Relationship to the prototype

The implementation, tests, demo, and recorded output supplied in `relindex_ports_prototype/` remain unchanged. Its README has been translated into English.
The contracts covered by the prototype's 23 test cases were migrated into common-layer tests organized by responsibility.
Additional checks cover boolean and floating-point key lookups through the public mapping, nonfinite values, both endpoints of empty plans, self-connections, and actual model ownership.
There are no compatibility aliases for the prototype API or automatic backend selection.

## Validation limits

Model semantics were compared for the small integer examples and runnable examples described here.
These checks do not establish correctness for arbitrary business models or support for every Pyomo configuration, version, or solver.
The library cannot detect ports an application never declares or incorrect quantity meanings, and it does not track expression changes after application.
