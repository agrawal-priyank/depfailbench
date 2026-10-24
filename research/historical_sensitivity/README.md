# Historical four-task primary-comparison sensitivity

This is a **retrospective illustrative calculation**, prepared on 24 October
2026 to complete the reporting follow-up for Reviewer 1 Comment 7. It does not
change the historical data, any evaluator, the frozen expanded analysis, or any
reported experimental result. It is not an original prospective sample-size
justification and is not “observed” or “achieved” power calculated from the
observed effect.

## Design and assumptions

- Four fixed tasks: T1, T2, T4 and T5.
- Twenty independently simulated C0 outputs and twenty C1 outputs for each task:
  **80 outputs per condition, 160 per tested model configuration**.
- The statistic is the equally weighted mean of the four task-specific pass-rate
  differences, as in the original `model_analysis` implementation. With equal
  cell sizes, it is also `(total C1 passes − total C0 passes) / 80`.
- Hypothetical C0 pass probability is 0.50 on every task. C1 has the same positive
  probability increment on all four tasks. All simulated outputs are independent
  Bernoulli draws within a simulated study. The tasks themselves are not sampled
  from a task population.
- These assumptions are transparent illustrative choices, not fitted estimates
  of the historical task probabilities. They are not guaranteed worst-case
  assumptions and do not establish power under heterogeneous task effects,
  dependent model outputs, provider changes or setting interactions.
- Twenty thousand simulated studies are used at each effect size, with fixed
  seed **20261024** and NumPy **2.3.5**. Common C0 draws and common C1 uniforms are
  reused across effect sizes to reduce noise in comparisons between neighbouring
  grid points. At each single effect, the 20,000 simulated studies are independent;
  estimates across effect sizes are correlated.

## Test matched to the historical primary comparison

The original implementation is preserved at
`work/release_v1.1.0/source/src/benchmark/full_analysis.py`. Its task-stratified
permutation test conditions on each task's pooled number of passes among forty
outputs, then redistributes twenty C1 labels. It samples 100,000 permutation
assignments and uses a plus-one Monte Carlo correction.

This sensitivity calculation uses the **exact conditional counterpart of that
same null distribution and statistic**. For task t with m_t pooled passes,

`P(X_t = x | m_t) = choose(m_t, x) choose(40 − m_t, 20 − x) / choose(40, 20)`.

The four task distributions are convolved. Writing X for the combined C1 pass
count and S for all pooled passes, the two-sided p-value includes all assignments
with `abs(2X − S) >= abs(2X_observed − S)`, including ties. Exact conditional
integration removes an unnecessary inner Monte Carlo layer; it does not rerun
or replace the original reported permutation calculations.

The two rejection thresholds are:

- **0.05:** the unadjusted two-sided per-model threshold.
- **0.025:** the conservative first-Holm threshold 0.05/2 for the two historical
  model comparisons. This is a per-comparison threshold sensitivity, **not** a
  simulation of power for the entire joint Holm procedure, which also depends
  on the other model's result.

## Results

The fixed coarse grid covers 0–50 percentage points in one-point increments.
The search then refines by 0.1 percentage point within one point either side of
each coarse estimated-80%-power crossing. No observed study effect determined
this grid.

| Threshold | Preceding grid gain | Estimated power there | First grid gain with estimated power ≥80% | Estimated power at crossing | Monte Carlo SE at crossing | Pointwise Monte Carlo Wilson 95% interval |
|---|---:|---:|---:|---:|---:|---|
| 0.05 | 22.5 pp | 79.780% | **22.6 pp** | 80.165% (16,033/20,000) | 0.282 pp of power | 79.607%–80.712% |
| 0.025 | 24.3 pp | 79.755% | **24.4 pp** | 80.175% (16,035/20,000) | 0.282 pp of power | 79.617%–80.722% |

The estimated crossings are approximate simulation/grid results, not exact
analytic minima. A simple pointwise Monte Carlo uncertainty bracket for the
crossing is 22.4–22.7 pp at 0.05 and 24.2–24.5 pp at 0.025: the lower endpoint's
Monte Carlo interval remains below 80%, while the upper endpoint's interval
starts at or above 80%. These are **not simultaneous confidence intervals for a
true minimum detectable effect**. Coarser prose such as “approximately 23 pp
unadjusted and 24–25 pp using the conservative first-Holm threshold” avoids false
precision. Parent review should choose the final presentation.

At zero effect the simulated rejection rates are 3.105% at 0.05 and 1.530% at
0.025. This is compatible with the conservatism of the discrete conditional test;
nominal significance thresholds need not be attained exactly.

## Computational checks and provenance

The script independently checks:

1. Exact combinatorial normalization, expected mean and variance for every one
   of the 41 possible original-task pooled pass counts.
2. The hypergeometric formula against exhaustive label-assignment enumeration
   for all pooled pass counts in a smaller four-per-arm block.
3. Fifty-two four-block patterns, including degenerate cases and fixed-seed
   random patterns, against direct **integer-coefficient convolution and exact
   rational arithmetic**. Every feasible two-sided rejection decision at both
   thresholds agrees. The largest probability-mass discrepancy from floating
   convolution is 5.55×10⁻¹⁷.
4. An exact rational fallback for any simulated conditional p-value within
   10⁻¹² of a rejection cutoff. No such fallback was needed in this run.

The output records the script and original-analysis SHA-256 hashes, NumPy
version, seed, assumptions, every grid result, rejection counts, Monte Carlo
standard errors and pointwise Wilson intervals. The original analysis hash is
checked before and after the calculation. All previous study files are retained
without modification. The script refuses to overwrite an existing results file.

Files in this new phase:

- `historical_primary_sensitivity.py` — self-contained simulation and numerical
  checks; imports no generated implementation or study execution code.
- `sensitivity_results.json` — preserved numerical results and provenance.
- `independent_review.json` — read-only review by a separate Codex agent,
  including all 87 grid rows and the method; no substantive bug found. This is
  not independent human scientific review.
- `README.md` — this methodological handoff, pending parent review before use.

The preparation uses no model calls, generated-program execution, external
services, or actual outcome data. The author has authorized closing this
reporting follow-up; these explicitly hypothetical assumptions do not require
a new experiment or change the scientific cohort. They should remain disclosed
if incorporated into the paper and reviewer response.
