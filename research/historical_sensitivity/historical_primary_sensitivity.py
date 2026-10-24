"""Retrospective illustrative sensitivity for the four-task historical endpoint.

Only simulated Bernoulli outcomes are used. This does not import study code,
read generated programs, execute services, make model calls, or change any
archived observation, scientific implementation, or confirmatory result.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from pathlib import Path
import hashlib
import json
import math
import time

import numpy as np


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
ORIGINAL_ANALYSIS = WORKSPACE / "work/release_v1.1.0/source/src/benchmark/full_analysis.py"
TASKS = ("T1", "T2", "T4", "T5")
N_PER_TASK_CONDITION = 20
REPLICATES = 20_000
SEED = 20261024
TARGET_POWER = 0.80
ALPHAS = (0.05, 0.025)
DENOMINATOR_PER_TASK = math.comb(40, 20)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integer_block_coefficients(total_passes: int, n: int = 20) -> list[int]:
    """Exact count of assignments giving x passes among n C1 labels."""
    size = 2 * n
    return [
        math.comb(total_passes, x) * math.comb(size - total_passes, n - x)
        if 0 <= x <= total_passes and 0 <= n - x <= size - total_passes
        else 0
        for x in range(n + 1)
    ]


def integer_convolution(left: list[int], right: list[int]) -> list[int]:
    out = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            out[i + j] += a * b
    return out


def exact_conditional_distribution(totals: tuple[int, ...]) -> tuple[list[int], int]:
    coefficients = [1]
    for total in totals:
        coefficients = integer_convolution(coefficients, integer_block_coefficients(total))
    return coefficients, DENOMINATOR_PER_TASK ** len(totals)


def exact_tail_p(totals: tuple[int, ...], c1_total: int) -> Fraction:
    coefficients, denominator = exact_conditional_distribution(totals)
    pooled = sum(totals)
    observed = abs(2 * c1_total - pooled)
    return Fraction(
        sum(v for x, v in enumerate(coefficients) if abs(2 * x - pooled) >= observed),
        denominator,
    )


BLOCK_PROBABILITIES = [
    np.array(integer_block_coefficients(total), dtype=np.float64) / DENOMINATOR_PER_TASK
    for total in range(41)
]
NEAR_THRESHOLD_EXACT_FALLBACKS = Counter()


@lru_cache(maxsize=None)
def rejection_vectors(totals: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Exact conditional tail, numerically convolved; exact cutoff fallback.

    C0/C1 have equal n within every task, so each conditional distribution is
    symmetric. For an observed C1 total x, the two-sided tail is twice the lower
    tail at min(x, pooled-x), capped at one. Impossible x values are never used.
    """
    distribution = np.array([1.0])
    for total in totals:
        distribution = np.convolve(distribution, BLOCK_PROBABILITIES[total])
    cdf = np.cumsum(distribution)
    pooled = sum(totals)
    lower_support = sum(max(0, t - 20) for t in totals)
    upper_support = sum(min(20, t) for t in totals)
    tails = np.ones(81, dtype=float)
    for x in range(lower_support, upper_support + 1):
        tails[x] = min(1.0, 2 * float(cdf[min(x, pooled - x)]))
    decisions = []
    for alpha in ALPHAS:
        reject = tails <= alpha
        for x in range(lower_support, upper_support + 1):
            if abs(tails[x] - alpha) <= 1e-12:
                reject[x] = exact_tail_p(totals, x) <= Fraction(str(alpha))
                NEAR_THRESHOLD_EXACT_FALLBACKS[str(alpha)] += 1
        reject.setflags(write=False)
        decisions.append(reject)
    return tuple(decisions)


def validation_checks() -> dict:
    checks = {}
    # Vandermonde normalization and moments for every possible original block.
    for m, probabilities in enumerate(BLOCK_PROBABILITIES):
        coefficients = integer_block_coefficients(m)
        assert sum(coefficients) == DENOMINATOR_PER_TASK
        xs = np.arange(21)
        mean = float(probabilities @ xs)
        variance = float(probabilities @ (xs - mean) ** 2)
        expected_var = 20 * (m / 40) * (1 - m / 40) * (20 / 39)
        assert math.isclose(float(probabilities.sum()), 1.0, abs_tol=1e-14)
        assert math.isclose(mean, m / 2, abs_tol=1e-13)
        assert math.isclose(variance, expected_var, abs_tol=1e-13)
    checks["all41_original_single_block_normalizations_and_moments"] = True

    # A separate exhaustive assignment enumeration for every success count of
    # a smaller equal-arm block verifies the hypergeometric combinatorial form.
    for m in range(9):
        enumerated = Counter(sum(i < m for i in chosen) for chosen in combinations(range(8), 4))
        calculated = integer_block_coefficients(m, n=4)
        assert [enumerated[x] for x in range(5)] == calculated
    checks["exhaustive_small_block_label_assignments"] = True

    rng = np.random.default_rng(SEED + 1)
    patterns = [(0, 0, 0, 0), (40, 40, 40, 40), (0, 10, 20, 40), (20, 20, 20, 20)]
    patterns.extend(tuple(sorted(map(int, r))) for r in rng.integers(0, 41, size=(48, 4)))
    maximum_absolute_error = 0.0
    for totals in patterns:
        coefficients, denominator = exact_conditional_distribution(totals)
        reference = np.array([float(Fraction(v, denominator)) for v in coefficients])
        actual = np.array([1.0])
        for m in totals:
            actual = np.convolve(actual, BLOCK_PROBABILITIES[m])
        error = float(np.max(np.abs(actual - reference)))
        maximum_absolute_error = max(maximum_absolute_error, error)
        assert error < 2e-15
        decisions = rejection_vectors(totals)
        lo = sum(max(0, t - 20) for t in totals)
        hi = sum(min(20, t) for t in totals)
        for x in range(lo, hi + 1):
            pooled = sum(totals)
            threshold = abs(2 * x - pooled)
            exact_p = Fraction(sum(v for i, v in enumerate(coefficients) if abs(2 * i - pooled) >= threshold), denominator)
            for decision, alpha in zip(decisions, ALPHAS):
                assert bool(decision[x]) == (exact_p <= Fraction(str(alpha)))
    checks["original_four_block_patterns_checked_with_exact_integer_arithmetic"] = len(patterns)
    checks["maximum_pmf_absolute_float_error_against_exact_rational"] = maximum_absolute_error
    checks["all_feasible_tail_decisions_match_exact_rational"] = True
    return checks


def wilson95(k: int, n: int) -> list[float]:
    z = 1.959963984540054
    p = k / n
    divisor = 1 + z * z / n
    center = (p + z * z / (2 * n)) / divisor
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / divisor
    return [max(0.0, center - half), min(1.0, center + half)]


def simulate() -> dict:
    started = time.monotonic()
    old_analysis_sha = sha256(ORIGINAL_ANALYSIS)
    checks = validation_checks()
    rng = np.random.default_rng(SEED)
    # Common random numbers across effects improve the precision of comparisons
    # between neighbouring grid points; every simulated output is independent
    # within a study under the assumed data-generating model.
    c0 = (rng.random((REPLICATES, 4, 20)) < 0.5).sum(axis=2)
    c1_uniform = rng.random((REPLICATES, 4, 20))
    results = {}

    def evaluate(effect_milli: int, grid: str) -> None:
        if effect_milli in results:
            if grid not in results[effect_milli]["grids"]:
                results[effect_milli]["grids"].append(grid)
            return
        delta = effect_milli / 1000
        c1 = (c1_uniform < (0.5 + delta)).sum(axis=2)
        totals = np.sort(c0 + c1, axis=1)
        observed = c1.sum(axis=1)
        rejects = np.zeros(2, dtype=np.int64)
        for group, x in zip(totals.tolist(), observed.tolist()):
            d = rejection_vectors(tuple(group))
            rejects[0] += bool(d[0][x])
            rejects[1] += bool(d[1][x])
        rates = {}
        for k, alpha in zip(rejects.tolist(), ALPHAS):
            rate = k / REPLICATES
            rates[str(alpha)] = {
                "rejections": k,
                "replicates": REPLICATES,
                "power_estimate": rate,
                "monte_carlo_standard_error": math.sqrt(rate * (1 - rate) / REPLICATES),
                "monte_carlo_wilson95": wilson95(k, REPLICATES),
            }
        results[effect_milli] = {"effect_pp": delta * 100, "p0_each_task": 0.5, "p1_each_task": 0.5 + delta, "grids": [grid], "thresholds": rates}

    # A fixed broad grid identifies the region; a predefined 0.1-pp refinement
    # surrounds each first crossing of 80% estimated power by one pp each side.
    for point in range(0, 501, 10):
        evaluate(point, "fixed_1pp_coarse_grid")
    crossing = {}
    for alpha in ALPHAS:
        crossing[alpha] = min(k for k, r in results.items() if r["thresholds"][str(alpha)]["power_estimate"] >= TARGET_POWER)
    for point in sorted({p for c in crossing.values() for p in range(max(0, c - 10), min(500, c + 10) + 1)}):
        evaluate(point, "predefined_0p1pp_refinement")

    grid_results = [results[k] for k in sorted(results)]
    sensitivity = {}
    for alpha in ALPHAS:
        key = str(alpha)
        above = [r for r in grid_results if r["thresholds"][key]["power_estimate"] >= TARGET_POWER]
        crossing_row = min(above, key=lambda r: r["effect_pp"])
        below = [r for r in grid_results if r["effect_pp"] < crossing_row["effect_pp"]]
        preceding = max(below, key=lambda r: r["effect_pp"])
        upper_below = [r for r in grid_results if r["thresholds"][key]["monte_carlo_wilson95"][1] < TARGET_POWER]
        lower_above = [r for r in grid_results if r["thresholds"][key]["monte_carlo_wilson95"][0] >= TARGET_POWER]
        sensitivity[key] = {
            "first_grid_effect_with_estimated_power_at_least_80pct": crossing_row,
            "preceding_grid_effect": preceding,
            "simulation_uncertainty_bracket_effect_pp": [max(r["effect_pp"] for r in upper_below), min(r["effect_pp"] for r in lower_above)],
            "simulation_uncertainty_bracket_interpretation": "Lower endpoint has pointwise Monte Carlo Wilson95 upper bound below80%; upper endpoint has pointwise Monte Carlo Wilson95 lower bound at least80%. This is an illustrative grid bracket, not a formal simultaneous confidence interval for a true MDE.",
        }
    assert sha256(ORIGINAL_ANALYSIS) == old_analysis_sha
    return {
        "status": "completed retrospective illustrative sensitivity; parent review required before manuscript use",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_program_executions": 0,
        "model_calls": 0,
        "real_outcomes_read_or_changed": False,
        "original_analysis_unchanged": True,
        "original_analysis_path": str(ORIGINAL_ANALYSIS.relative_to(WORKSPACE)),
        "original_analysis_sha256": old_analysis_sha,
        "script_sha256": sha256(Path(__file__)),
        "numpy_version": np.__version__,
        "tasks": list(TASKS),
        "n_per_task_condition": N_PER_TASK_CONDITION,
        "n_per_condition_per_model": 80,
        "n_total_per_model": 160,
        "independently_simulated_studies_per_effect": REPLICATES,
        "seed": SEED,
        "target_power": TARGET_POWER,
        "baseline_pass_probability_each_task": 0.5,
        "effect_structure": "Same positive C1-minus-C0 pass-probability increment on all four fixed tasks; independent Bernoulli outputs within every task/condition; no task-population sampling.",
        "statistic": "Equally weighted mean of four task-specific C1-minus-C0 pass-rate differences, equivalently total(C1passes-C0passes)/80 because task arms have equal n20.",
        "conditional_null": "For each task condition on pooled successes among40 outputs; assign20 C1 labels; convolve four hypergeometric distributions; two-sided tail includes ties |2X-S| >= |2Xobserved-S|.",
        "relation_to_original": "Same task-stratified conditional permutation null and statistic as historical model_analysis. Original numerical analysis samples100000 permutation assignments with plus-one correction; this sensitivity integrates that conditional null exactly rather than simulating an inner permutation sample.",
        "alpha_interpretation": {"0.05": "Unadjusted two-sided per-model threshold.", "0.025": "Conservative first-Holm threshold .05/2 for two model comparisons; not an estimate of power of the complete joint Holm procedure."},
        "randomness": "Common C0 draws and common C1 uniforms across effect sizes; outputs within each simulated study are independent; Monte Carlo estimates across grid points are correlated.",
        "grid_definition": "Fixed positive-effect grid0–50pp by1pp, then refine by0.1pp within1pp either side of each coarse estimated80% crossing. No observed study effect used.",
        "qualification": "Retrospective design sensitivity under explicitly hypothetical assumptions. Does not show achieved power, equivalence, original prospective justification, population generality, or power for heterogeneous task effects, dependent calls or setting interactions. No frozen scientific analysis or original result is changed.",
        "validation": checks,
        "near_cutoff_exact_rational_fallbacks": dict(NEAR_THRESHOLD_EXACT_FALLBACKS),
        "conditional_pattern_cache": rejection_vectors.cache_info()._asdict(),
        "sensitivity": sensitivity,
        "grid_results": grid_results,
        "elapsed_seconds": time.monotonic() - started,
    }


def main() -> None:
    output = ROOT / "sensitivity_results.json"
    if output.exists():
        raise FileExistsError("Preserve the existing sensitivity result; choose a new phase for a new run.")
    result = simulate()
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), "validation": result["validation"], "sensitivity": result["sensitivity"], "elapsed_seconds": result["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
