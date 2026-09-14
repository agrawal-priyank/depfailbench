# DepFailBench

DepFailBench evaluates LLM-generated FastAPI services under controlled downstream dependency failures. It distinguishes clean correctness, successful recovery, safe termination, and unsafe or unavailable outcomes. The software is a research benchmark, not a production-readiness certification.

DepFailBench is authored and maintained by [Priyank Agrawal](https://orcid.org/0009-0004-3230-8277), Independent Researcher, New York, NY, United States.

## Completed study

The full study contains four fixed tasks: T1 Product Proxy, T2 Paginated Catalog, T4 Order Payment, and T5 Object Upload. Two model configurations and two specification conditions, with 20 generations per cell, produced 320 unchanged programs. Each saved program has three oracle-hardened evaluations with zero categorical disagreements. The earlier two-task, 16-program pilot is separate and excluded from those results.

C0 is a baseline contract, not a uniform absence of operational guidance: catalog and upload baselines already include safeguards. C1 adds a bundled resilience specification. See [pre-generation protocol](docs/FULL_STUDY_PROTOCOL.md) and [release guide](docs/REPRODUCING_FULL_STUDY.md).

The root files preserve the pilot plan and also supply the model configuration and T1/T4 scaffolds reused by the full study. Their planning-status values are historical. Full-study prompts, T2/T5 scaffolds, and the frozen manifest are under `full_study/`; `full_study_schedule.csv` lists the 320 prespecified generation slots. Generated programs and evaluation records are in the release archive rather than the Git repository.

## Installation

Use Python 3.12. From this source directory:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m pytest -q tests
```

The pinned environment is the reference evaluation environment. Statistical analysis additionally uses `numpy==2.3.5`.

## Five-minute walkthrough

```sh
.venv/bin/depfailbench validate-references --repetitions 3
.venv/bin/python examples/transient_transport.py
```

The first command validates the T1/T4 handwritten controls; full-study T2/T5 controls are covered by the repository tests. The second command injects the same `503 -> 200` dependency sequence into two T1 controls. The naive service stops after one call and returns a safe 503 response. The resilient service retries once and returns the valid product after two calls. Neither command generates model outputs.

The complete saved study is distributed as the versioned `DepFailBench_Source_and_Data.zip` release artifact. After extracting it, reproduce one saved program with:

```sh
.venv/bin/python -m benchmark.full_eval \
  ../data/artifacts/full_v1_T1_C1_openai_gpt56sol_g01 \
  ../single-evaluation.json
```

The output records clean qualification, primary pass status, every scenario outcome, downstream-call traces, and task-specific state. It can be inspected without provider credentials.

For all 320 saved programs and the statistical analysis, follow the [reproduction instructions](docs/REPRODUCING_FULL_STUDY.md). Analysis and evaluation need no provider account or API key. Generation is a separate, explicitly billable operation and is not required to reproduce saved results.

## Software organization

- `src/benchmark/emulator.py`, `runner.py`, and `oracle.py`: T1/T4 fault traces and checks.
- `src/benchmark/full_tasks.py`: T2/T5 dependencies, fixtures, and outcome checks.
- `src/benchmark/full_eval.py`: full-study artifact loading and scenario evaluation.
- `src/benchmark/full_batch_eval.py`: fresh-process batch execution with hard time limits.
- `src/benchmark/full_analysis.py`: fixed-task analysis of saved evaluation records.
- `src/benchmark/task_api.py`, `task_registry.py`, and `adapter_eval.py`: versioned extension interface, explicit manifest loading, and task-agnostic evaluation.
- `full_study/`: frozen full-study prompts, scaffolds, and their manifest.
- `tests/`: reference, regression, and evaluator checks.

The historical T1/T2/T4/T5 evaluator remains fixed so the published 320-program study can be replayed exactly. New tasks can use the versioned manifest-backed adapter interface without registering task IDs in core code. A task author still supplies the semantic oracle, scenarios, dependency request contract, and observable state; these cannot be inferred safely from HTTP status alone. See the runnable [task-adapter guide](docs/ADDING_TASKS.md).

## Scope and interpretation

The four tasks use short, isolated requests and emulated dependency faults. They exclude concurrency, long-lived state, real distributed transactions, cascades, and calibrated network latency. Retry-After is zero in the rate-limit fixtures. Safe failure is distinct from successful recovery; only specified fault scenarios allow it to count as a pass.

The evaluator registers a fresh generated module for every probe, validates exact request/response/state contracts, combines application and simulated dependency time, and separately checks finite timeout behavior against a hanging dependency. A machine-readable ledger identifies 53 programs that move from submitted primary pass to hardened failure. No generated source was repaired. See [release notes](CHANGELOG.md).

## Citation, documentation, and licenses

Please cite DepFailBench using [CITATION.cff](CITATION.cff). Version 1.1.0 is the Array-revision source release; its matched data archive contains the hardened replays and external case-study records. Version 1.0.2 and [doi:10.5281/zenodo.22699095](https://doi.org/10.5281/zenodo.22699095) preserve the earlier SoftwareX submission state.

[User guide](docs/USER_GUIDE.md), [result schema](docs/RESULT_SCHEMA.md), [task-adapter guide](docs/ADDING_TASKS.md), [pilot methodology](docs/METHODOLOGY.md), [contribution rules](CONTRIBUTING.md). Software source code is licensed under the MIT License in the sole canonical `LICENSE` file. Study data is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0), as specified in [DATA_LICENSE.md](DATA_LICENSE.md).
