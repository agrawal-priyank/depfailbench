# Historical pre-generation full-study protocol and budget

**Status note (release v1.0.2):** This is the frozen pre-generation planning record. The study was completed and released on 10 September 2026. Statements below about pending gates, projected cost, estimated effort, and a working JSS target are preserved as historical protocol context; they do not describe the current release. For T1 alone, C0 included the exact clean fixture example while C1 gave only the schema, so that condition contrast is not a pure resilience-instruction effect. See [Reproducing the completed study](REPRODUCING_FULL_STUDY.md) for the final artifact layout, results, and verification route.

Design version 1.0, September 10, 2026. Working paper: “Can LLM-Generated Backend Services Survive Dependency Failures?” Working venue: Journal of Systems and Software (JSS). This is a design lock, not an executable benchmark release or a submission-readiness claim. No new paid generations were started.

## Research questions and scope

RQ1 (primary): Within each model, does adding explicit resilience requirements increase the proportion of generated services that are clean-correct and satisfy every applicable fault oracle?
RQ2: How do clean correctness, fault recovery, bounded safe failure, and unsafe outcomes differ between conditions?
RQ3 (descriptive): Which failure mechanisms recur across the four selected backend interaction patterns?

The estimand is performance on these fixed tasks and model versions under this one-shot generation procedure. Do not generalize statistically to all backend tasks or rank the providers by unequal effort settings. C0 fault behavior is a stress-test outcome, not proof of violating an undisclosed requirement. C1 is a bundle of requirements, so the study does not identify which instruction caused an improvement.

## Task coverage

| ID | Task | Distinct behavior and required checks |
|---|---|---|
| T1 | Product Proxy (existing) | One read dependency; exact valid payload, transient/persistent 503, timeout, bounded 429 handling, malformed response. |
| T2 | Paginated Catalog (new) | Sequential pages from one dependency; complete ordered result, no duplicate/missing items after retry, bounded requests, continuation-token validation. Clean fixture has three pages. Faults affect a fixed middle page; terminal and malformed-page failures must not return a fabricated complete result. |
| T4 | Order/Payment (existing) | Side-effecting POST with provider idempotency; lost response after commit, duplicate charging, valid confirmation, and local/external-state agreement. |
| T5 | Object Upload (new) | Idempotent PUT to one object store; exact key/content and checksum acknowledgment; lost acknowledgment after commit, safe reattempt, persistent failure, rate limit, malformed acknowledgment. No claim of success without validated receipt; no wrong-key or wrong-content writes. |

T3 and T6 remain reserved. This reduces implementation breadth while retaining two read and two write patterns. No concurrency, service mesh, Kubernetes, cascading faults, or agent repair loops. T2 requires a per-logical-page retry bound; T5 requires a per-object bound. The current three-attempt whole-request check must not be reused blindly for T2.

Before generation, each new task must have a complete visible API/state contract, identical functional content in C0/C1, immutable fixtures and a scenario-oracle matrix. This document selects the coverage; exact task prompts and implementation hashes remain a release gate. Contract corrections in T1/T4 must be logged and applied to both conditions where appropriate.

## Sample and execution

4 tasks × 2 models × 2 conditions × 20 independent generations = **320 fresh artifacts**, 160 per provider. Models: gpt-5.6-sol and claude-opus-5, medium effort, no tools, one user turn, code-only output, no repair. Pin a snapshot if offered; otherwise record returned model identity, API version, timestamps and limitations of mutable aliases.

Use the saved seeded schedule, interleaved by task/model/condition within each replication block. An equal generation index does not imply a statistically paired sample. Record prompt/scaffold/environment hashes, request IDs, usage, finish reasons, raw responses and source hashes. Independent means distinct provider calls; test probes and repeat executions are not extra generated samples.

The existing 16 artifacts are a separate protocol-development pilot. They do not count toward 320 and will not enter the primary estimates. Publish their original and corrected results and explain the post-pilot lifecycle/oracle amendments.

Twenty replications per cell is a precision/feasibility choice, not a power calculation based on optimistic pilot effects. Each model-condition has 80 implementations across fixed tasks. At worst-case Bernoulli variance, an approximate unadjusted 95% half-width for the model-level difference is about 15.5 percentage points; per-task estimates are much less precise. Do not promise detection of small effects or increase n after viewing significance.

## Outcomes and analysis

Primary outcome per generated artifact: 1 only if it constructs, passes clean qualification, and passes all applicable fault oracles; otherwise 0. This unconditional measure avoids the selection problem in comparing APR only among clean-qualified programs.

Report the C1−C0 risk difference separately for each model, equally weighting the four tasks. Report numerator/denominator per task and model. Use stratified label permutation within task/model for the primary difference (100,000 permutations, fixed seed 20260910, plus-one p-value); Holm-adjust the two model-level p-values at familywise 0.05. This tests a prespecified procedure on fixed tasks, not a population of tasks.

Report 95% stratified artifact-bootstrap intervals (10,000 resamples within task/model/condition, fixed seed) as approximate uncertainty intervals. Do not use scenario probes as independent observations. If a cell is all zero or one, disclose bootstrap degeneracy and provide a conservative bound from simultaneous Wilson intervals: eight task-condition proportions per model, each at 1−0.05/8 coverage, propagated through the equal-weight difference. Include ordinary Wilson intervals for descriptive per-cell proportions.

Secondary: CCR; conditional APR; per-artifact mean fault-recovery fraction (macro-average equally over tasks, with denominator explicit); counts of safe/unsafe/availability outcomes; attempts per logical operation; duplicate side effects; consistency flags. Keep pilot SRR definitions traceable: its pooled probe rate is not silently substituted for the full-study task-balanced measure. Separate unconditional operational success from conditional resilience. Subgroup/failure-taxonomy analyses are descriptive; no additional confirmatory p-values.

## Exclusions, errors and retries

Do not repair code or discard syntax, import, contract, clean-path or valid-response truncation failures; they remain generated failures in the primary denominator. Preserve missing slots separately and never score missing evidence as zero.

Authentication, transport, rate-limit and provider-server errors that return no usable generation are operational failures. Retain attempt metadata, retry only that slot with a logged reason and at most two retries. An ambiguous timeout can have consumed tokens: count it against budget conservatively. Never rerun a completed slot because its code is poor. Do not automatically retry truncated but completed responses.

Repeat evaluation three times for each artifact; substantive outcome disagreements are investigation flags, not majority votes. Separate semantic results from UUIDs and wall latency. If the evaluator needs a correction, version it, preserve prior results, rerun every affected artifact, and disclose the change. Do not tune oracles to favor a model. Any change to prompts/scaffolds or task contracts after full generation starts creates a new study version; never silently combine versions.

## Validation and release gate

1. Complete T2/T5, contract/oracle tables and reference fixtures; validate all reference outcomes.
2. Extend the runner, artifact metadata and plan validation beyond pilot-only task IDs and generation indices 1–2. Existing pilot commands cannot execute this schedule unchanged.
3. Test lifecycle failure and cleanup, public response validity, stable operation identity, per-operation retry bounds, malformed/committed outcomes and alternate non-paid labels. For T4 with an external charge, predefine terminal failure versus unresolved semantics without a hidden arbitrary string whitelist. Unrecognized semantics must be flagged for blinded review.
4. Fix the completeness distinction: all slots present is different from all apps constructing and from an error-free evaluator. Validate truncated-response and provider-error accounting.
5. Create and test the analysis script using synthetic edge cases, missing/invalid artifacts, and all-zero/all-one cells before viewing full-study outcomes.
6. Freeze exact dependency versions, prompt/scaffold/scenario/oracle hashes, execution schedule and analysis code in a release manifest. The design is locked here; these implementation gates are still pending.
7. Verify current model availability, rates and available credits. Run only after release gates pass; no automatic follow-up generation or scheduling is created by this document.

## Budget

Standard API prices verified September 10: OpenAI $4 input / $20 output per million tokens; Anthropic $5 / $25. No batch/cache discounts assumed. Token usage includes returned reasoning/thinking within output usage and must not be double counted.

The eight OpenAI pilot samples average 455.25 input and 2559.625 output tokens; Anthropic averages 747.25 input and 2076 output. At 160 samples each, linear extrapolation is **$17.38** ($8.48 OpenAI + $8.90 Anthropic). New tasks may produce longer code, so use **$35 as the planning allowance**, not a spending guarantee.

At the proposed per-call guards of 2,000 input and 12,000 output tokens, the 320 successful calls have a **$87.36 token envelope** ($39.68 OpenAI + $47.68 Anthropic), excluding tax, failed/retried requests, pricing changes, and any uncounted token categories. Proposed operational stop: **$100 estimated API spend**, checking completed plus in-flight worst-case cost before each dispatch. These guards and ledger are requirements to implement, not existing enforced controls. Recompute if any actual prompt exceeds 2,000 tokens.

Estimated hands-on work: 12–20 hours for two tasks and validation, 4–6 hours for analysis/budget controls, 3–5 hours for run audit, and 12–20 hours for manuscript/figures/release: **31–51 hours**, a planning estimate. At the previously discussed 6–8 hours/week, roughly 4–9 weeks; September 30 is not a credible commitment for this scope. Provider runtime is additional unattended elapsed time and depends on latency/rate limits.

## Literature position and venue

BaxBench evaluates backend functional correctness and security; BackendForge evaluates contract-defined end-to-end backend generation. Our candidate distinction is controlled runtime dependency failure and recovery with explicit resilience requirements. These two comparisons do not establish exhaustive novelty: finish the matrix covering software aging, agent fault injection and generated-system resilience before claiming priority.

JSS remains the working research-paper target; venue suitability depends on the final contribution and results. SoftwareX/Software Impacts are potential distinct software publications, not alternate names for this same study. SANER is the separate next-paper track and adds workload; reassess it rather than assume both deadlines can be met.

Sources: [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Anthropic Opus pricing](https://www.anthropic.com/claude/opus), [BaxBench](https://arxiv.org/abs/2502.11844), [BackendForge](https://arxiv.org/abs/2607.11042).
