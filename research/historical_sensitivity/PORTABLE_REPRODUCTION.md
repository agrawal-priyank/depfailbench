# Portable reproduction of the historical sensitivity calculation

This wrapper reproduces the same **retrospective, hypothetical four-task design
sensitivity** recorded in `sensitivity_results.json`. It requires the unchanged
Supplementary Material S2 ZIP and the supplied numerical helper; it does not
require the author's workspace, provider credentials, or the generated services'
runtime dependencies.

## Files and environment

Keep these files together, as supplied in the reporting-additions package:

- `reproduce_historical_sensitivity.py` — portable wrapper.
- `historical_primary_sensitivity.py` — hash-pinned original numerical helper.
- `sensitivity_results.json` — hash-pinned original results for comparison.

Use Python with **NumPy 2.3.5** installed. No FastAPI, model SDK, network connection
or generated-program execution is required for this calculation. In a suitable
Python environment, the dependency can be installed separately with:

```sh
python -m pip install numpy==2.3.5
```

Installing a dependency is a separate environment-setup step; the reproduction
wrapper itself makes no network calls.

## Command

From any working directory, provide the S2 archive and a new output path:

```sh
python /path/to/reproduce_historical_sensitivity.py \
  /path/to/Supplementary_Material_S2.zip \
  --output /path/to/new_sensitivity_reproduction.json
```

The output's parent directory must already exist. Existing output files are
refused rather than overwritten. If the three supplied helper files are not
together, their paths can be given explicitly:

```sh
python /path/to/reproduce_historical_sensitivity.py \
  /path/to/Supplementary_Material_S2.zip \
  --math-script /path/to/historical_primary_sensitivity.py \
  --original-results /path/to/sensitivity_results.json \
  --output /path/to/new_sensitivity_reproduction.json
```

The wrapper does not offer an option to replace or disable its expected hashes.
It verifies:

| Input | Required SHA-256 |
|---|---|
| Unchanged S2 ZIP | `4a70538f1fdf7efb6ad0a7186b9a8e3c044fd0d89b74e77969590bd081bc2bfa` |
| Numerical helper | `0b7e67ffb74b385cce36a86e68f473a5d74f305d9f52ffe008678e8c155fbb2f` |
| Original sensitivity results | `b9f6588da5db45a976f06c6b29136af7b5f5b3fc7897b8bf0db6c5a417266f83` |
| Archived historical analysis provenance file | `3916c833bd28da13868e06c89b279e597e0adb4fa2f06b1329587b1330efee36` |

The S2 member read for historical provenance is exactly:

```text
DepFailBench_Array_Revision/historical/release_v1.1.0/source/src/benchmark/full_analysis.py
```

## What is executed and what is compared

Only the verified numerical helper is executed, under a non-main namespace. The
wrapper stages that helper and the historical-analysis **bytes** in a temporary
workspace, redirects the helper's three workspace paths there, and invokes its
`simulate()` function. The helper's ordinary file-writing `main()` is not run.
The archived historical analysis is read and hashed only: **it is never imported
or executed**. No generated application or other archived code is executed, and
the full S2 archive is not extracted.

The output contains the reproduced numerical results and a
`portable_reproduction` receipt. Every original result field is compared except
the top-level run timestamp, computational runtime and status text. The
comparison includes all 87 grid rows, rejection counts, Monte Carlo standard
errors and intervals, grid crossings, sensitivity summaries, simulation inputs,
method text and original provenance hashes. Integer values must match exactly;
finite floating-point values use relative tolerance 10⁻¹² and absolute tolerance
10⁻¹⁴ to accommodate negligible arithmetic rounding. Scientific assumptions,
rejection counts and the seed cannot change under that tolerance.

The original helper, results, review and README remain unchanged. Reproduction
does not rerun the empirical study or revise its inference. Its results retain
the original limitations: independent simulated Bernoulli outputs, a 50% C0
probability on each fixed task and uniform positive effects. The first estimated
80%-power grid crossings are approximate sensitivity summaries, not exact
analytical minimum detectable effects or original prospective justification.

## Verification supplied with this package

- `portable_reproduction_results.json` — successful numerical reproduction and
  provenance receipt.
- `portable_reproduction_verification.json` — successful reproduction from an
  unrelated temporary working directory, unchanged original-file hashes, and
  negative tests for overwrite refusal, wrong input hashes and numerical
  discrepancies.
- `portable_wrapper_review.json` — separate Codex agent's read-only guard and
  provenance review; no substantive issue found. This is not independent human
  scientific review.
