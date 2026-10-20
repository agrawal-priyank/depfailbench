# Authenticated generation and saved-response recovery

The expanded study has a prepared authenticated sender plus local recovery and
billing reconciliation. No API account compatibility or model results are
established by these software tests. The draft study remains unfrozen and
paid execution remains unauthorized.

## Permission and isolation

`ExecutionPermit` binds a specific cohort, expiry, reviewed numeric spending
limit, prices, exact prompts/configurations, dependency lock, analysis and
implementation hashes. The validation permission cannot generate main outputs;
main also requires the final frozen/authorized study declaration. No permission
file is generated or approved automatically. Changing a bound input requires
review and a new explicit permission, rather than silently continuing.

A `mock_validation` permission explicitly prohibits paid execution and requires
HTTPX MockTransport. A `live` permission prohibits substituting mock HTTP
responses. Simulated transport checks remain labelled synthetic, even when they
exercise the live-ledger branch. Simulation and actual ledgers cannot be reused
interchangeably. An existing spending limit/permission cannot change silently.

The authenticated sender permits only POST requests to the exact five selected
HTTPS endpoints. Credentials are loaded at dispatch and injected into headers,
not saved request records. Redirects and ambient proxies are disabled; transport
connection retries are zero. The existing explicit three-attempt service-error
rule remains unchanged. Provider parallelism remains two, except xAI one.
Required secret names are OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
XAI_API_KEY and MISTRAL_API_KEY. Add keys through secret settings, never source
files or conversation messages. Account/key scope must be checked separately.

## Interrupted output

Received payload bytes are flushed and synced before parsing. Start/header and
completion journals, exact request/configuration records and atomic exclusive
artifact publication support recovery after a stopped process. The completion
metadata is published last. A slot lock prevents recovery during an active
request and is released by the OS on process termination.

`python -m benchmark.expanded.provider_recovery ARTIFACT --ledger LEDGER`
opens a recovery-only ledger and replays saved bytes locally, without keys,
network requests, new generation or code repair. It checks slot/request/prompt,
configuration/provenance and completed-wire hashes. Different existing output
is never overwritten. Complete, refused, truncated, empty and partial outputs
retain their status; a partial output is not replaced by a fresh response.

Store=false remains selected for the supported stateless APIs. Recovery does
not assume that a response can be retrieved from a provider later. An accepted
request without recoverable output stays unfilled and paused for operator
review. It is not counted as a returned model failure and cannot silently be
reissued. Recovery of an older pre-journal rehearsal is not claimed; the new
journal applies prospectively. A missing completion timestamp is explicitly
represented in the recovery journal; the original attempt start supplies a
fallback metadata time when a terminal response was received before a crash.

## Billing reconciliation

Unknown charges continue to hold the reserved allowance. Recovery can finish
an interrupted ledger record using saved usage but does not overwrite an
already recorded charge. `SpendingLedger.reconcile_cost` requires an explicit
amount (including explicit zero), a reason and a nonempty evidence file; it
records the evidence hash and previous/new cost. Clearing a pause separately
requires evidence and rejects unresolved charges or an exceeded total limit.
The original response/usage records remain intact. Recovery-only access stays
available after a permission expires and cannot dispatch another request.

Reservations are reviewed allowances, not provider-enforced maximum bills.
Grok's visible-output cap excludes reasoning; actual usage and provider spend
settings must be reviewed before paid validation and main authorization.

## Remaining run gates

Validate this exact code snapshot on Linux and from an installed package;
prepare checkpointed generation/evaluation/storage; verify account/model access
and required secrets; review prices, numeric spending and validation execution;
then run 160 separately excluded actual API-validation outputs. Inspect usage
and finish reasons, settle uniform pre-main corrections and freeze the full
main protocol before the 4800 main generations. A mock rehearsal does not
satisfy the actual API-validation gate. No manuscript change follows from this
software-preparation step.

## Official API references checked 20 October 2026

- OpenAI streaming: https://developers.openai.com/api/docs/guides/streaming-responses
- OpenAI storage: https://developers.openai.com/api/docs/guides/migrate-to-responses
- OpenAI request IDs/retries: https://developers.openai.com/api/reference/python
- Claude authentication: https://platform.claude.com/docs/en/api/overview
- Claude stream errors: https://platform.claude.com/docs/en/api/errors
- Gemini stateless storage: https://ai.google.dev/gemini-api/docs/interactions-overview
- Gemini authentication: https://ai.google.dev/gemini-api/docs/get-started
- xAI Responses: https://docs.x.ai/developers/rest-api-reference/inference/responses
- Mistral authentication/streaming: https://docs.mistral.ai/api/endpoint/chat
