# Release notes

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
