# Expanded API and fixed study assets

`benchmark.expanded` is separate from the historical evaluator. Public reusable components include `contracts` (settings/tasks/scenarios), `planning` (structural prompt/allocation validation), `evaluate`/`worker` (isolated observed-time evaluation), `collect` (saved-record identities), `reclassify`/`oracles` (saved-observation classification), `failure_reporting`, `repeat_audit`, and `report_collection`. Provider modules preserve the reviewed request/response/accounting mechanisms and support mocked validation; no paid campaign launcher is supplied by this release.

Run `python -m benchmark.expanded preflight` to inspect resources without a generated-program run or model call. The command validates 4,320 main and 144 separate validation coordinates across nine configurations. Its legacy draft-status text is not execution permission and is retained with the frozen scientific source. The current dataset records completed execution separately.

All E1–E8 C1 prompts preserve C0 verbatim and append the common 122-word resilience block. Settings, scaffold, contracts and all frozen/amendment JSONs remain unchanged from the executed commit. Scientific source hashes are supplied in `SCIENTIFIC_SOURCE_MANIFEST.json`; packaging/version/docs changes do not redefine the study.

The historical generic TaskAdapter API remains available through `benchmark.task_api`, `task_registry` and `adapter_eval`, with a handwritten example in `examples/external_task/`. That example demonstrates registration and execution, not generated-study performance or automatic validation of new task oracles.

Fresh generated-program execution is deliberately absent from the default quick start. The API can evaluate untrusted saved source only when a user deliberately invokes it in an appropriately isolated, credential-free Linux environment. Such reruns are new measurements and must not replace the archived records silently.
