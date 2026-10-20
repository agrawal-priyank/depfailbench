# Expanded Array study: local preparation

This is a **draft under local validation**, not a frozen or executed model study.
The original four-task release, prompts, evaluators and results remain unchanged.
The expanded evaluator is in `benchmark.expanded`; it does not use the historical
virtual-time-plus-wall-time measurement to classify expanded programs.

## Reproduce the local preparation

Use Python 3.12 and the exact `requirements.lock`, with this repository's `src`
on `PYTHONPATH` or an installed package. No model credentials are needed for these
commands, and none of them calls a model API.

```sh
python -m pip install -r expanded_study/requirements-analysis.txt
python -m benchmark.expanded preflight --output results/expanded/plan_preview
python -m pytest -q
python -m benchmark.expanded validate-references \
  --deadlines 1 2 5 --repeats 3 --output results/expanded/reference_validation
python expanded_study/analysis.py --synthetic-demo \
  --output results/expanded/synthetic_analysis/summary.json
python -m benchmark.expanded.provider_dry_run \
  --output results/expanded/provider_rehearsal
python -m benchmark.expanded.collection_dry_run --mode reference-controls \
  --output results/expanded/collection_controls
python -m benchmark.expanded.report_collection \
  results/expanded/collection_controls/collection \
  --output results/expanded/collection_control_exports
python -m benchmark.expanded.collection_dry_run --mode synthetic-reporting \
  --output results/expanded/collection_synthetic_reporting
```

Preflight checks all sixteen prompts against their shared source and scaffold,
then creates deterministic previews of 4,800 main slots and 160 separate API
validation slots. These previews are **not** evidence that any model generation
has happened. `expanded_study/study.json` keeps frozen and paid-execution flags
false. No paid execution command is supplied by this local preparation module.

The complete contracts are in `expanded_study/tasks/`. The normal common block,
dependency schemas, examples, versions, starter code and numeric timing settings
are byte-identical in C0/C1. C1 appends only `prompts/resilience.md`. The exact full
prompts and their hashes are included in the preview.

## Tasks, data and failure checks

Expanded E1/E3/E5/E7 map to historical T1/T2/T4/T5 respectively; E2/E4/E6/E8 are
shipping quotes, activity aggregation, inventory reservations and preference
replacement. Historical identifiers and unused planning slots are preserved.
The four new contracts define tie-breaking, integer money/quantities, opaque
pagination, duplicate/conflict semantics, retry-safe identities, truthful
receipts, replacement defaults and observed final state.

`task_contracts.json` lists each task's functional and fault checks. Expanded
functional qualification includes every declared ordinary, alternate-data and
business/input-boundary check, including the appropriate 4xx responses. A
program failing this stage stays in the unconditional denominator; later fault
probes are marked unexecuted, not silently counted as successful or removed.

The hand-written references are controls, not generated main-study data.
Deliberately faulty controls cover missing retries, partial or duplicated pages,
duplicate side effects, false success, wrong object identity, patch-versus-
replacement errors, unavailable startup and synchronous event-loop blocking.

The reporting dry-run uses 4,800 explicitly synthetic records, never generated
research outcomes. It enforces the complete allocation and prompt metadata,
rejects validation/missing/duplicate records, reconciles failure counts and
per-scenario denominators, and computes the prespecified primary and secondary
statistics. It preserves shared baselines in bootstrap contrasts and includes
nonzero exact-binomial bounds for boundary cases. Install the separately pinned
analysis-only NumPy dependency; it is not a new generated-program dependency.

## Actual-time evaluation

Each scenario runs in a fresh worker process with fresh dependency and app state.
Intentional repeated logical requests stay together inside their scenario.
Imports, factory construction and lifespan startup are measured separately and
have a 15-second startup watchdog. Each public request then has its own timing
handshake and an independent parent-process watchdog. Blocking Python code cannot
disable this watchdog by blocking the child's event loop.

HTTPX custom transports do not implement real network timeout behavior by
themselves. This dependency transport consumes actual monotonic elapsed time and
honors the supplied read timeout. Timeout delays are not instant exceptions later
added to a synthetic clock. Response classification uses recorded request wall
time with the fixed **50 ms** tolerance. An additional 150 ms of IPC termination
slack is not part of the pass threshold; any parent watchdog intervention fails.

Startup, worker errors, returned program failures, response/body checks, each
dependency attempt and duration, cancellation, observed side effects, final stock,
stored objects/preferences and declared application state are recorded. The worker
receives no provider credentials. It runs with the fixed local package environment;
process separation is a timing boundary, not a claim of a full security sandbox.

```sh
python -m benchmark.expanded evaluate path/to/saved/artifact \
  --deadline 1 --output results/expanded/artifact-deadline-1.json
```

The saved artifact has `app.py` and `metadata.json`, including task E1–E8 and
condition C0/C1. A returned generation marked truncated, incomplete, refused or
no_code remains unsuccessful; it is not repaired or regenerated. Re-executing
saved code does not call a model API.

## Still required before main generation

Local reference/defect validation is only one part of readiness. Completing the
reviewed live sender/recovery support, account access,
separately reviewed 160-output API validation, measured-usage cost review and
main-study freeze remain prerequisites. Verify target-platform behavior before
using these measurements as the main study; local macOS validation does not prove
Linux/container timing reproducibility. The proposed $200 spending envelope is
not permission to launch generation and is not a provider-enforced hard cap.

The main denominator stays 4,800, with the original 320 and the excluded API
validation outputs kept distinct. Preserve all outputs and records. A negative or
inconclusive result is not grounds for another paid generation campaign.

The manually dispatched `expanded-local-validation.yml` workflow prepares the
same checks for Ubuntu 22.04/Python 3.12.14. It uses no model keys or generation
commands. Preparing the workflow is not evidence it has run; executing it may
consume GitHub Actions compute minutes.

## Provider adapter checkpoint

The provider request/response adapters, SSE assembly and durable spending/attempt
ledger have been implemented and tested **offline**. The rehearsal executes the
160 validation allocations against hand-written HTTP fixtures. Its records are
marked synthetic in both the report and artifact metadata. The fixture programs
are response-format examples, not business-correct reference programs or model
samples. The primary analyzer recognises synthetic metadata as well as top-level
flags, so it cannot label an intact mock artifact as a real result.

The selected routes are OpenAI Responses, Anthropic Messages, Gemini Interactions,
xAI Responses and Mistral Chat Completions. Null sampling controls remain omitted;
standard service tiers are explicit where supported. No extra instructions or
prompt rewrites are introduced by an adapter. Request/setting/prompt hashes,
requested and resolved model IDs, exact response payload bytes, streamed events,
partial text, stop reasons and raw usage counters are preserved separately.
Reasoning text is excluded from app.py. Usage handling avoids double-counting
reasoning and recognises explicit cache counts and unknown billing.

The rehearsal accepts only HTTPX MockTransport and never loads credentials. It
does not have a live execution switch. There are no implicit SDK retries. The
selected 30-second connection/1,800-second overall allowance and provider
concurrency limits are implemented. Only explicit transient HTTP statuses or a
connection failure before acceptance/content can retry, at most three times.
Accepted ambiguous requests pause for recovery; refusals, partial/truncated
responses, absent code and syntax errors are retained without replacement.
Long Retry-After, exhausted retries, incompatible responses or missing usage
remain visible and pause dispatch as applicable.

The SQLite ledger reserves pending/unknown costs atomically and records actual
token estimates even if they exceed an allowance. An overrun pauses subsequent
dispatch. Estimates use explicitly supplied dated rates and are not invoices.
Reservations are operational allowances, not provider-enforced cost guarantees;
Grok reasoning remains outside its visible-output cap. Interrupted/inflight
attempts and existing artifact directories cannot be silently overwritten or
regenerated. The separate [20 October authenticated sender and recovery preparation](LIVE_EXECUTION_READINESS.md)
supersedes the earlier recovery/reconciliation implementation-pending status.
Actual account compatibility, spending authorization and the excluded paid
validation batch remain open.

Documentation checked 19 October 2026: [OpenAI reasoning](https://developers.openai.com/api/docs/guides/reasoning),
[Claude Messages](https://platform.claude.com/docs/en/api/messages/create),
[Gemini Interactions](https://ai.google.dev/api/interactions-api.md),
[xAI Responses](https://docs.x.ai/developers/rest-api-reference/inference/responses),
and [Mistral Chat](https://docs.mistral.ai/api/endpoint/chat). These document API
schemas, not account access or successful live requests by this project.

## Saved-program collection and deadline reporting

`benchmark.expanded.collect` validates artifact coordinates, exact saved prompts,
configurations, source hashes and study/scaffold/task/environment provenance
before execution. Actual artifacts also require saved raw provider attempts.
Service-only slots remain unfilled; no subset can silently supply a complete
main-study denominator. Synthetic controls cannot mix with real programs.

The fixed matrix is three deadlines (1/2/5 seconds) by three repeat IDs for each
same saved program. Jobs are deterministically shuffled with the selected seed.
Each scenario still resets app/dependency state, with the task's intentional
multi-request replay sequence kept within its scenario. Collection records have
source/environment/implementation fingerprints and exclusive atomic writes.
Restart verifies and reuses complete records rather than replacing or rerunning
them. Changed artifacts, measurement code, assets, environments or saved records
stop collection. The artifact source and evidence are checked before/after each
evaluation, with every input rechecked at completion.

Repeat 1 is always selected; repeats 2/3 audit reproducibility. Pass/category,
successful output and observed state/effects are compared within each deadline;
ordinary timing variation and nonsemantic error text are not disagreements.
The raw timing/error records remain available. Any behavior disagreement is
reported and blocks confirmatory analysis pending review; it never selects the
best repeat. Main analysis additionally rejects repeat IDs other than 1 and
explicitly flagged disagreements.

`benchmark.expanded.report_collection` exports the chosen-repeat program table,
cell Wilson intervals, per-scenario reached and unconditional denominators,
one shared failure taxonomy with disjoint priority counts plus overlapping flags,
same-program deadline transition counts (including worsening), and descriptive
aggregate deadline estimates with nominal bootstrap intervals and conservative
exact-binomial bounds. Deadline tables introduce no additional confirmatory
tests. Within-deadline intervals do not test cross-deadline changes. The full
primary and three secondary inference tables remain limited to the complete
4,800-output main allocation at the 1-second deadline and prespecified repeat.

Each selected row links back to its full immutable record; those records retain
dependency requests, state, receipts, timing and error details. Per-program and
per-probe counts are separate. Repeats do not create additional independent
programs. In a complete main collection the matrix has **43,200 program-level
evaluation records**, while the generated-program denominator remains **4,800**
and the repeat-1 deadline exports have **14,400 rows**.

Dependency attempts include monotonic start/end offsets relative to their public
request and the observable gap after the preceding completed attempt. Startup
dependency work has a separately labelled initialization origin. These gaps can
include application processing and scheduling; they are not labelled pure retry
backoff. They support an auditable cumulative-deadline timeline. Request wall
time remains the pass/fail timing measure; offsets and gaps are diagnostics only.

```sh
python -m benchmark.expanded.collect path/to/saved/main/artifacts \
  --cohort main --output results/expanded/main_collection
python -m benchmark.expanded.report_collection results/expanded/main_collection \
  --output results/expanded/main_exports
```

`--artifact-id` selects an explicitly diagnostic subset; such a subset never
produces full-cohort inference. Output directories retain evidence; use a new
collection/export path for a documented reanalysis rather than overwriting an
earlier run. These commands evaluate saved programs only and contain no model
generation calls. Re-execution and collection controls consume local compute.
