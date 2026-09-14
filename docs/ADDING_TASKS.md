# Adding a task without editing DepFailBench internals

DepFailBench 1.1 exposes a versioned, manifest-backed task-adapter API. An adapter owns the public invocation, dependency request contract, scenarios, observable state, and behavioral oracle. The shared evaluator owns artifact loading, fresh-module isolation, application lifespan, deadlines, deterministic seeds, and result serialization.

The complete runnable example is in `examples/external_task`. It deliberately lives outside `benchmark.task_specs` so its test proves that registration does not require a core source edit.

## Required files

Create an importable Python module containing one `TaskAdapter` instance, a JSON manifest that names it as `module:attribute`, condition prompts, and a scaffold with the existing `create_app(transport, settings)` signature. Every adapter needs exactly one clean scenario, listed first. Each scenario declares the outcome classes accepted by the task contract.

Implement these boundaries:

1. `make_dependency` supplies deterministic behavior for one scenario.
2. `invoke` calls the generated application's public endpoint.
3. `inspect_dependency_request` validates the downstream method, path, and payload.
4. `snapshot_dependency` exports attempts, side effects, virtual time, and violations.
5. `snapshot_state` exports application state when the semantic contract needs it.
6. `classify` assigns a behavioral outcome from the public response, trace, and state.

Task adapters are trusted executable code. A manifest selects adapters explicitly; DepFailBench does not scan installed packages or sandbox third-party adapters.

## Run the example

From the repository root:

```sh
PYTHONPATH="src:examples/external_task" python -m benchmark.adapter_eval \
  examples/external_task/artifact /tmp/external-example.json \
  --manifest examples/external_task/task_manifest.json
```

The expected outcomes are resilient success for `clean` and `transient_503`, safe failure for `persistent_503`, and a passing full contract. The example is an extensibility demonstration; it is not a fifth generated task and is excluded from the paper's four-task prompt comparison.

For a scheduled batch, pass the same manifest to `benchmark.full_batch_eval --task-manifest`. New generation schedules may also use `benchmark.full_generate --task-manifest --schedule`. Registering an adapter never adds it to an existing study or changes an existing estimand.
