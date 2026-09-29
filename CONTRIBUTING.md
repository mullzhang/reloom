# Development and validation

Use Python 3.12+, `uv`, and Git.
`mise.toml` specifies the locally verified Python 3.14.6 and uv 0.11.16 versions.

## Environment

```sh
uv sync --locked --extra pyomo --group solver
```

The `dev` group contains pytest, Ruff, mypy, and the Markdown validation library.
The `solver` group contains HiGHS for examples and tests. It is not a required dependency of the distributed package.
`relindex` is pinned to Git commit `7ef35a66d910b389ad38b2a197765388adf2e86a`.

## Routine checks

```sh
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest
uv run --no-sync python scripts/check_docs.py
```

`mise run setup` and `mise run check` use the same environment and checks.
Strict type checking covers the public library under `src/reloom`.
The boundary with Pyomo's untyped API uses `Any`; the common layer preserves type parameters.

`check_docs.py` renders Markdown to HTML and checks relative links, code syntax, code fences, and trailing whitespace.
It also executes the README's Python example. Rendered HTML is written to `build/docs/`.

To run only the common-layer tests:

```sh
uv run --no-sync pytest tests/test_contracts.py tests/test_assembly.py
```

Integration tests are skipped when Pyomo or HiGHS is not installed.
Use the environment setup above to run the complete suite.

## Distributions

```sh
uv run --no-sync python scripts/verify_wheel.py
uv run --no-sync python scripts/verify_wheel.py --python 3.12
```

The script performs these steps in order:

1. Build an sdist and wheel from the source tree, then check that every file matches a wheel rebuilt from the sdist.
2. Build a dependency wheel from the pinned `relindex` Git commit.
3. Install the core package in a fresh virtual environment, verify that Pyomo, PuLP, HiGHS, and NumPy are absent, and test the common-layer contracts.
4. Install Pyomo and HiGHS in a separate fresh environment, then run copied tests and four standalone examples outside the repository.

The script does not inherit `PYTHONPATH` and checks that the imported `reloom` is outside the source tree.
The wheel includes the library code and type information from `src/reloom`, excluding the prototype and examples.
The sdist includes the examples and tests.

If a local `relindex` Git repository is available, use the existing commit without fetching it again.
The script leaves that working tree untouched, exports the specified commit into a temporary directory, and builds there.

```sh
uv run --no-sync python scripts/verify_wheel.py --relindex-source ../relindex
```

The artifacts are `dist/reloom-0.1.0-py3-none-any.whl`, `dist/reloom-0.1.0.tar.gz`, and `dist/dependencies/relindex-0.1.0-py3-none-any.whl`.
When installing the generated wheel into another environment, also specify the dependency wheel:

```sh
uv venv /tmp/reloom-demo
uv pip install --python /tmp/reloom-demo/bin/python \
  'dist/reloom-0.1.0-py3-none-any.whl[pyomo]' \
  dist/dependencies/relindex-0.1.0-py3-none-any.whl highspy==1.15.1
```

`tool.uv.sources` defines a development source and is not included in the wheel's dependency metadata.
These checks use a `relindex` wheel built from the pinned commit.
They do not verify `pip install reloom` through PyPI.
Before public release, separately verify that `relindex>=0.1.0,<0.2` can be obtained from a public package index.

## Construction benchmarks

```sh
uv run --no-sync python benchmarks/build.py --output build/benchmark.json
```

See the [benchmark document](docs/benchmarks.md) for the measurement conditions and recorded results.
When adding features, verify contract correctness first, then measure cost changes with the same data, repetition count, and comparison implementations.

## CI

[GitHub Actions](.github/workflows/ci.yml) runs static checks, the full test suite, documentation checks, and installed-wheel validation on Python 3.12 and 3.14.
The action configuration follows the [official setup-uv documentation](https://github.com/astral-sh/setup-uv).
Report local validation separately from results actually obtained on GitHub.
