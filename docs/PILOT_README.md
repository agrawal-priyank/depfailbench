# DepFailBench

DepFailBench is a deterministic fault-injection benchmark for measuring how LLM-generated FastAPI services behave when runtime dependencies fail. It separates clean-path functional correctness from operational resilience and records recovery, safe failure, unsafe behavior, retry amplification, duplicate side effects, and final-state consistency.

The v1.0 pilot contains the locked T1 Product Proxy and T4 Order/Payment tasks. The full study reserves six tasks, but T2, T3, T5, and T6 are intentionally not invented during pilot execution.

## What the pilot tests

- T1: clean response, transient and persistent HTTP 503, timeout, HTTP 429 with `Retry-After`, and malformed HTTP 200.
- T4: the same applicable faults plus timeout before commit and an ambiguous outcome in which the payment commits but its response is lost.
- Conditions: C0 functional-only and C1 with explicit resilience requirements.
- Design: 2 tasks × 2 model families × 2 conditions × 2 independent generations = 16 artifacts.

The scope deliberately excludes concurrency, cascading or compound failures, Kubernetes, and service meshes.

## Install

Python 3.12 is required.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

## Validate the deterministic controls

```bash
.venv/bin/depfailbench validate-references --repetitions 3
```

This runs the handwritten `reference_naive` and `reference_resilient` controls. All non-wall-clock observations must be identical across repetitions, the naive controls must pass the clean contract, and the resilient controls must satisfy every scenario oracle.

## Preview and generate the pilot

Previewing makes no provider calls:

```bash
.venv/bin/depfailbench generate
```

Actual generation is deliberately explicit and non-overwriting:

```bash
export OPENAI_API_KEY='...'
export ANTHROPIC_API_KEY='...'
.venv/bin/depfailbench generate --execute
```

Each artifact retains the exact prompt, source, provider response, model identity, request ID, usage, generation time, prompt hash, scaffold hash, and dependency-lock hash. Provider keys are never written to disk.

### Generate securely with GitHub Actions

The manual **OpenAI pilot** workflow generates and evaluates only the eight frozen OpenAI slots. To use it:

1. In the GitHub repository, open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `OPENAI_API_KEY` containing a newly created project key.
3. Open **Actions → OpenAI pilot**, select **Run workflow**, and confirm the run.
4. When it finishes, download the `depfailbench-openai-pilot-*` artifact from the workflow run.

The encrypted secret is supplied only to the generation job. It is not written to the repository, generated artifacts, benchmark results, or workflow logs. The workflow is manual-only, so pushes and pull requests cannot trigger billable model calls.

## Run the complete pilot

```bash
.venv/bin/depfailbench pilot
```

The command creates:

- `results/pilot/artifact_manifest.jsonl`
- `results/pilot/observations.jsonl`
- `results/pilot/observations.csv`
- `results/pilot/summary.json`
- `results/pilot/pilot_report.md`

It exits with status 2 when any of the 16 planned artifacts are absent. Use `--allow-incomplete` only to inspect readiness; missing slots are never replaced by synthetic data.

## Docker

```bash
docker build -t depfailbench .
docker run --rm depfailbench
```

To evaluate locally generated artifacts and retain results:

```bash
docker compose run --rm depfailbench
```

## Outcome classes and measures

Every probe receives one of four mutually exclusive outcomes: `resilient_success`, `safe_failure`, `unsafe_failure`, or `availability_failure`. The report calculates clean correctness rate (CCR), scenario recovery rate (SRR), application pass rate (APR), mean retry amplification factor, duplicate side effects, and state-consistency failures. Exact definitions are in [docs/METHODOLOGY.md](docs/METHODOLOGY.md); the machine-readable fields are in [docs/RESULT_SCHEMA.md](docs/RESULT_SCHEMA.md).

## Research framing

DepFailBench does not claim that resilience of LLM-generated software is wholly unexplored. Its narrower contribution is controlled runtime downstream-dependency fault injection and measurement of recovery behavior in generated backend services.

## Reproducibility and reuse

- `protocol.json` is the machine-readable protocol lock.
- `generation_plan.json` fixes all 16 generation slots.
- `requirements.lock` records the validated dependency versions.
- `prompts/` and `scaffolds/` contain the exact generation inputs.
- `ARTIFACT_CONTRACT.md` defines the only editable surface.
- The MIT license permits reuse and extension.

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for extension instructions and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules.
