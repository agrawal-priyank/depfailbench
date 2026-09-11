# User guide

For the completed four-task study use [Reproducing the full study](REPRODUCING_FULL_STUDY.md). The commands below are the legacy pilot interface. The full-study runner is `python -m benchmark.full_eval` or `benchmark.full_batch_eval`.

## Commands

`depfailbench validate-references` runs both handwritten controls against every pilot scenario. Use this first after installation.

`depfailbench generate` prints the immutable generation slots. Add `--execute` only when provider credentials are available and model calls are intended. Select individual slots by repeating `--slot ARTIFACT_ID`.

`depfailbench evaluate ARTIFACT_DIRECTORY` clean-qualifies and evaluates one artifact. Only a clean-correct implementation advances to hidden fault probes.

`depfailbench pilot` evaluates every slot in `generation_plan.json` and writes a complete report. It fails closed when artifacts are missing; `--allow-incomplete` is a readiness inspection option.

## Artifact layout

Each generated artifact has its own immutable directory:

```text
artifacts/T1_C0_openai_gpt56sol_g1/
├── app.py
├── metadata.json
├── prompt.txt
└── raw_response.json
```

The benchmark never overwrites an existing directory. This prevents an accidental rerun from replacing an independent generation.

## Adding a model family

Add a model entry and balanced slots to `generation_plan.json`, then add a provider adapter to `src/benchmark/generate.py`. Provider-specific effort settings must be recorded rather than assumed equivalent. Do not alter prompts between model families.

## Adding a task after the pilot

1. Freeze the visible C0 and C1 specifications.
2. Add a minimal scaffold with the same dependency-injection boundary.
3. Define deterministic fault scripts.
4. Define the oracle before generating artifacts.
5. Create naive and resilient handwritten controls.
6. Prove deterministic repetition with tests.
7. Increment the protocol version and regenerate prompt hashes.

New tasks must not introduce concurrency, cascading failures, Kubernetes, or service-mesh behavior without an explicit scope decision.

## Interpreting failures

- A clean failure contributes to CCR and stops further probing for that artifact.
- A C0 fault-probe failure describes observed operational behavior; it is not a violation of a hidden requirement.
- A safe failure terminates within bounds and does not fabricate success or corrupt state.
- An unsafe failure includes invalid success, duplicate effects, or inconsistent state.
- An availability failure includes an unhandled exception, deadline breach, or more than three dependency attempts.
