# Expanded-study public error status policy

Version: `written-contract-2026-10-20`. Applies to every model, configuration and instruction condition. The task and prompt bytes are unchanged.

When a task requires a particular public status, that code remains mandatory. For a dependency failure whose exact public error code was not specified, the accepted dependency-error family is **502, 503 or 504**. This does not accept arbitrary client errors, HTTP 500, false success, a missed deadline or a failure where recovery is required.

| Written requirement | Status criterion |
|---|---|
| E1 missing product; E2 no valid quotes | 404 |
| E2/E6/E8 invalid public input | 422 before dependency work |
| E6 insufficient stock; second request with conflicting identity/payload | 409 |
| E2 invalid outer quote response or conflicting quote identity | 502 |
| E3 cursor cycle or conflicting duplicate; E4 conflicting duplicate | 502 |
| E8 malformed/mismatched receipt | 502 |
| E8 dependency unavailability or an unconfirmed write | 503 |
| E6 lost acknowledgment after commit, when confirmation cannot be obtained | 503 with UNRESOLVED state; if the fixed scenario permits recovery, 503 alone does not pass the recovery requirement |
| Other malformed/mismatched responses, unavailable dependencies or exhausted request budgets without an explicit error code | 502, 503 or 504, with all other applicable checks satisfied |
| Clean behavior or a fault for which the scenario requires feasible recovery | Correct 200 response and complete required work |

The E6 503 clause concerns its stated lost-acknowledgment case; it does not introduce an exact-code requirement for a malformed receipt. E4's text prescribes 502 for conflicting event data, while requiring bounded truthful failure for a cursor cycle without prescribing a particular code. These distinctions come from the common task text.

The paginated cumulative-budget scenario still requires recovery at the longer allowances where the prescribed work fits; a safe error is accepted only when the selected budget is insufficient. Existing timing tolerance, attempt limits, dependency contracts, complete responses, confirmed receipts, idempotency, duplicate-effect checks, stock consistency and truthful application state remain in force.

`benchmark.expanded.oracles.expected_status` implements the task/scenario matrix. `benchmark.expanded.reclassify.policy_manifest()` emits its complete deadline/public-request table and the conditional reservation rule.

For saved **validation** traces, the reclassification command creates a separate derived collection. It links each record to the original hash, retains the actual measured environment and implementation, and records the new classification implementation and policy. It does not run saved programs or make model requests. It rejects changed task assets, incomplete traces and unrelated measurement changes. It cannot reclassify the main cohort or overwrite original records. Repeat 1 remains selected in advance; repeats 2/3 remain reproducibility audits.

Preserve prior scores and explain the correction when reporting validation history. An excluded configuration check does not estimate main-study performance or establish equivalence between instruction groups.
