# Model construction benchmarks

On 2026-09-29, the same sparse linear model was built using three implementations.
`reloom` validates mappings, expression ownership, and connection contracts, so its construction time was longer than the direct implementations in these measurements.
This record measures the cost of the added contracts; it does not demonstrate a performance improvement.

## Conditions

- macOS 27.0, arm64, Python 3.14.6.
- `reloom` 0.1.0, `relindex` 0.1.0 (commit `7ef35a6`), Pyomo 6.10.1, HiGHS 1.15.1.
- Two sizes: 100 nodes and 5,000 nodes. Each node has four source keys, with one additional isolated target.
- Each target requires 1, while the isolated target requires 0. Nonnegative variables on the source keys are aggregated and equated to these requirements. The optimal objectives are 100 and 5,000, respectively.
- One warmup and five measured runs per condition. Implementation order rotates on each run, and garbage collection runs before construction.
- The table reports median construction time. Memory is the peak Python allocation measured with `tracemalloc` in a separate run, excluding the full memory usage of native libraries.

The baselines use `relindex.group_by` directly and indexed handwritten Python with a `defaultdict` initialized with every target group.
Both retain empty targets and create the same variables, equalities, and objective.
Neither baseline scans all candidates for each target.
The direct implementations do not include equivalent `reloom` contract checks.

## Results

| Source keys | Implementation | Median construction time | Peak Python memory |
| ---: | --- | ---: | ---: |
| 400 | reloom | 14.68 ms | 0.68 MiB |
| 400 | Direct relindex | 2.09 ms | 0.32 MiB |
| 400 | Indexed Python | 1.54 ms | 0.24 MiB |
| 20,000 | reloom | 797.22 ms | 15.35 MiB |
| 20,000 | Direct relindex | 109.38 ms | 11.72 MiB |
| 20,000 | Indexed Python | 61.35 ms | 10.41 MiB |

With 20,000 source keys, `reloom` took about 7.3 times as long to construct the model as direct `relindex`, and about 13.0 times as long as indexed Python.
These measurements apply to this model and environment; they do not establish timing ratios for other sizes, structures, or complete business models.

## Breakdown

The table shows medians for 20,000 source keys. The sum of the stage medians need not equal the median total time.

| Implementation | Relations and indices | Native model | Aggregation | Connection planning | Constraint attachment |
| --- | ---: | ---: | ---: | ---: | ---: |
| reloom | 35.38 ms | 32.12 ms | 376.07 ms | 191.27 ms | 162.30 ms |
| Direct relindex | 51.66 ms | 32.45 ms | 12.78 ms | Nearly 0 | 12.27 ms |
| Indexed Python | 3.05 ms | 33.33 ms | 11.82 ms | Nearly 0 | 13.23 ms |

`sum_over` performs grouping, summation, and validation of values before and after summation as one public operation, so all of these are included in reloom's aggregation stage.
Grouping in the direct implementations is included under relations and indices.
Connection planning includes construction of the target `Indexed` values and validation of ports and plans. Constraint attachment also includes revalidation immediately before `apply()`.
Use total construction time as the primary comparison; individual stage columns do not measure equivalent internal work.

Solving was measured in a separate single run per condition, outside the construction measurements.
For the larger case, the times were 475.61 ms for reloom, 528.24 ms for direct relindex, and 455.22 ms for indexed Python.
These single measurements include solver initialization and model conversion, so they do not support a ranking of solver performance.
Every condition produced the same expected optimal objective.

## Reproduction

```sh
uv run --no-sync python benchmarks/build.py \
  --sizes 100 5000 --fanout 4 --repeats 5 --output build/benchmark.json
```

The [benchmark script](../benchmarks/build.py) and [JSON containing every run](benchmarks/2026-09-29.json) are included.
Future performance work should measure repeated expression and schema checks while retaining validation before exposure and immediately before application.
Before adding caching, verify that it detects changes to mutable named expressions and parameters.
