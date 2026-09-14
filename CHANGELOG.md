# Release notes

## 1.1.0 - 2026-09-14

- Harden task oracles against unsupported success, wrong downstream requests, schema type confusion, ambiguous payment state, state leakage, excessive attempts, and deadline evasion.
- Add a hanging-dependency guard that distinguishes configured or application-enforced timeouts from the evaluator's outer watchdog and charges cumulative timeout budgets to the request deadline.
- Replay all 320 saved programs three times with zero categorical or timeout-guard disagreements and publish a 53-program submitted-to-hardened change ledger.
- Add externally sourced Stripe 15.6.1 and Seam 3.12.0 contract cases: 18 cases and 54 repeat-stable formal records.
- Add the versioned manifest-backed task-adapter interface, an out-of-tree runnable task, and generation/batch-evaluation support.
- Add a validated post-hoc failure-strategy taxonomy, task-composition and generation-order sensitivity analyses, and revised figures.
- Keep `LICENSE` as the sole software-license file and `DATA_LICENSE.md` as the separate research-data license.

## 1.0.2 - 2026-09-10

- Keep one canonical `LICENSE` plus the exact `Licence.txt` filename required by the SoftwareX template; remove the redundant `LICENSE.txt` alias.
- Register modules consistently in both evaluator entry points and validate analysis inputs against all 320 scheduled artifact identities.
- Clarify completed-study provenance, provider-attempt accounting, prompt-condition limitations, license scopes, and historical workflow status.
- Include the separate 16-program pilot with original and corrected reports in the source/data archive.
- Publish the audited full-study source and data artifact under doi:10.5281/zenodo.22699095.

Experimental prompts, fault contracts, generated source, and original full-study records are unchanged. Generation used commit `a434549`, with operational resumption at `97bf6e2`. The tagged software release is [v1.0.2 on GitHub](https://github.com/agrawal-priyank/depfailbench/releases/tag/v1.0.2); the full-study archive is [doi:10.5281/zenodo.22699095](https://doi.org/10.5281/zenodo.22699095).

## 1.0.1 - 2026-09-10

- Correct dynamic module registration in the full-study evaluator, with a regression fixture.
- Reconcile the README with the completed four-task study; retain historical pilot instructions separately.
- Include full-study inputs, licensing, and documentation in installed package data.
- Document analysis replay, fresh evaluation, and a bounded extension example.
- Prepare the initial SoftwareX research release.

## 1.0.0 - 2026-09-03

- Added deterministic T1 Product Proxy and T4 Order/Payment fault scenarios.
- Added naive and resilient reference controls and four-way outcome classification.
- Added CCR, SRR, APR, retry-amplification, duplicate-effect, and state-consistency reporting.
- Added the balanced 16-artifact generation plan for two model families and two prompt conditions.
- Added fail-closed clean qualification and explicit reporting of missing or invalid artifacts.
- Added a command-line interface, Docker packaging, continuous tests, documentation, and release metadata.
- Clarified the visible T4 state-observation contract and embedded the actual starter file in every prompt before model generation; recorded as protocol v0.4.1.
