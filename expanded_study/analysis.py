"""Fixed-allocation reporting; --synthetic-demo never represents study results."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

from benchmark.expanded.contracts import TASKS, is_functional, scenarios
from benchmark.expanded.failure_reporting import PRIORITY, failure_flags
from benchmark.expanded.planning import allocation, assets_root

NORMAL = NormalDist()


def wilson(k, n, alpha=.05):
    z = NORMAL.inv_cdf(1-alpha/2)
    p = k/n
    denominator = 1 + z*z/n
    center = (p + z*z/(2*n))/denominator
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def exact_binomial(k, n, alpha):
    """Clopper-Pearson bounds by monotone binomial-tail inversion."""
    def cdf(p):
        return sum(math.comb(n, x)*p**x*(1-p)**(n-x) for x in range(k+1))
    def upper_tail(p):
        return sum(math.comb(n, x)*p**x*(1-p)**(n-x) for x in range(k, n+1))
    lower = 0.0
    upper = 1.0
    if k:
        lo, hi = 0.0, k/n
        for _ in range(60):
            mid = (lo+hi)/2
            if upper_tail(mid) < alpha/2:
                lo = mid
            else:
                hi = mid
        lower = (lo+hi)/2
    if k < n:
        lo, hi = k/n, 1.0
        for _ in range(60):
            mid = (lo+hi)/2
            if cdf(mid) > alpha/2:
                lo = mid
            else:
                hi = mid
        upper = (lo+hi)/2
    return [lower, upper]


def convolution(left, right):
    result = [0.0]*(len(left)+len(right)-1)
    for i, a in enumerate(left):
        if a:
            for j, b in enumerate(right):
                result[i+j] += a*b
    return result


def exact_primary(block_counts):
    distribution = [1.0]
    successes = observed = 0
    for k0, k1 in block_counts:
        total = k0+k1
        pmf = [math.comb(total, x)*math.comb(10-total, 5-x)/math.comb(10, 5)
               if 0 <= x <= total and 0 <= 5-x <= 10-total else 0.0 for x in range(6)]
        distribution = convolution(distribution, pmf)
        successes += total
        observed += k1
    threshold = abs(2*observed-successes)
    p = sum(v for i, v in enumerate(distribution) if abs(2*i-successes) >= threshold)
    return min(1.0, max(0.0, p))


def holm(values):
    ordered = sorted(values, key=lambda key: 1.0 if values[key] is None else values[key])
    previous = 0.0
    adjusted = {}
    for index, key in enumerate(ordered):
        value = 1.0 if values[key] is None else values[key]
        previous = max(previous, min(1.0, (len(values)-index)*value))
        adjusted[key] = None if values[key] is None else previous
    return adjusted


def summarize(rows, *, bootstraps=20000, seed=20261019, root=None):
    root = assets_root(root)
    schedule, _ = allocation(root)
    expected = {s["artifact_id"]: s for s in schedule}
    observed = {}
    synthetic = {bool(row.get("synthetic_data") or row.get("metadata", {}).get("simulation_only") or
                      row.get("metadata", {}).get("synthetic_data")) for row in rows}
    if len(synthetic) != 1:
        raise ValueError("do not mix synthetic and actual records")
    for row in rows:
        if row.get("evaluation_repeat", 1) != 1:
            raise ValueError("primary analysis uses prespecified repeat 1 only")
        if row.get("reproducibility_disagreement"):
            raise ValueError("repeat disagreement requires review before confirmatory analysis")
        if any(type(row.get(field)) is not bool for field in ("primary_pass", "clean_qualified")):
            raise ValueError("program outcomes must be explicit Booleans")
        metadata = row.get("metadata", {})
        identity = metadata.get("artifact_id")
        if identity not in expected or identity in observed:
            raise ValueError("duplicate or unexpected artifact, including excluded validation")
        slot = expected[identity]
        if metadata.get("cohort") != "main":
            raise ValueError("only the frozen main cohort belongs in primary analysis")
        for key in ("task", "condition"):
            if row[key] != slot[key]:
                raise ValueError("evaluation coordinates differ from allocation")
        for key in ("configuration_id", "model_id", "prompt_sha256", "block_id"):
            if metadata.get(key) != slot[key]:
                raise ValueError(f"artifact metadata differs from plan: {key}")
        if row.get("deadline_s") != 1:
            raise ValueError("this primary analysis requires the prespecified 1-second outcomes")
        checks = row.get("observations", [])
        if row["primary_pass"] and (not row["clean_qualified"] or len(checks) != len(scenarios(row["task"])) or not all(c["pass"] for c in checks)):
            raise ValueError("inconsistent AllPass result")
        ids = [c["scenario"] for c in checks]
        if len(set(ids)) != len(ids) or set(ids) - set(scenarios(row["task"])):
            raise ValueError("unknown or duplicated scenario observation")
        if row["clean_qualified"] and set(ids) != set(scenarios(row["task"])):
            raise ValueError("qualified output has missing fault observations")
        derived = bool(row["clean_qualified"] and len(checks) == len(scenarios(row["task"]))
                       and all(c["pass"] for c in checks) and not row.get("integrity_error")
                       and not row.get("generation_failure"))
        if row["primary_pass"] != derived:
            raise ValueError("primary outcome does not match its recorded checks")
        observed[identity] = row
    if set(observed) != set(expected):
        raise ValueError("incomplete main study; do not silently reduce denominators")
    cells = defaultdict(list)
    blocks = defaultdict(lambda: {"C0": [], "C1": []})
    for identity, row in observed.items():
        slot = expected[identity]
        cells[(row["task"], slot["configuration_id"], row["condition"])].append(row)
        blocks[slot["block_id"]][row["condition"]].append(int(row["primary_pass"]))
    if any(len(group) != 30 for group in cells.values()) or any(len(v) != 5 for block in blocks.values() for v in block.values()):
        raise ValueError("analysis needs 30 per cell and five per condition in every block")
    design = json.loads((root / "study.json").read_text())
    rng = np.random.default_rng(seed)
    config_stats, bootstrap_curves, cell_report, scenario_report, failure_report = {}, {}, [], [], []
    for config in design["configurations"]:
        config_id = config["id"]
        difference = variance = bound_low = bound_high = 0.0
        draws = np.zeros(bootstraps)
        boundary = False
        for task_id in TASKS:
            pair = []
            intervals = []
            for condition in ("C0", "C1"):
                group = cells[(task_id, config_id, condition)]
                k, n = sum(r["primary_pass"] for r in group), len(group)
                pair.append(k/n)
                intervals.append(exact_binomial(k, n, .05/16))
                sign = 1 if condition == "C1" else -1
                draws += sign*rng.binomial(n, k/n, size=bootstraps)/n/8
                variance += (k/n)*(1-k/n)*n/(n-1)**2/64
                boundary |= k in {0, n}
                cell_report.append({"task": task_id, "configuration": config_id, "condition": condition,
                                    "successes": k, "n": n, "rate": k/n, "wilson95": wilson(k, n),
                                    "functional_qualified": sum(r["clean_qualified"] for r in group)})
                disjoint, overlap = Counter(), Counter()
                for row in group:
                    if row["primary_pass"]:
                        continue
                    flags = failure_flags(row)
                    disjoint[next(x for x in PRIORITY if x in flags)] += 1
                    overlap.update(flags)
                assert sum(disjoint.values()) == n-k
                failure_report.append({"task": task_id, "configuration": config_id, "condition": condition,
                                       "failed_programs": n-k, "disjoint_priority_counts": dict(disjoint),
                                       "overlapping_reason_counts": dict(overlap)})
                for scenario in scenarios(task_id):
                    reached = [o for r in group for o in r.get("observations", []) if o["scenario"] == scenario]
                    passed = sum(o["pass"] for o in reached)
                    scenario_report.append({"task": task_id, "configuration": config_id, "condition": condition,
                                            "scenario": scenario, "generated_n": n, "reached_n": len(reached),
                                            "passed_n": passed, "rate_among_reached": passed/len(reached) if reached else None,
                                            "rate_all_generated": passed/n})
            difference += (pair[1]-pair[0])/8
            bound_low += (intervals[1][0]-intervals[0][1])/8
            bound_high += (intervals[1][1]-intervals[0][0])/8
        config_stats[config_id] = {"risk_difference": difference, "bootstrap95": np.quantile(draws, [.025, .975]).tolist(),
                                   "conservative_exact95": [bound_low, bound_high], "boundary_cells_present": boundary,
                                   "hc3_variance": variance, "baseline": config["baseline"], "model_id": config["model_id"]}
        bootstrap_curves[config_id] = draws
        if config["baseline"]:
            block_pairs = []
            for task_id in TASKS:
                for round_id in range(1, 7):
                    block = blocks[f"{task_id}:{config_id}:round-{round_id}"]
                    block_pairs.append((sum(block["C0"]), sum(block["C1"])))
            config_stats[config_id]["raw_p"] = exact_primary(block_pairs)
    primary = {k: v for k, v in config_stats.items() if v["baseline"]}
    adjusted = holm({k: v["raw_p"] for k, v in primary.items()})
    for key, value in adjusted.items():
        primary[key]["holm_p"] = value
    secondary = {}
    for config in design["configurations"]:
        if config["baseline"]:
            continue
        other = config["id"]
        baseline = next(c["id"] for c in design["configurations"] if c["baseline"] and c["model_id"] == config["model_id"])
        difference = config_stats[other]["risk_difference"] - config_stats[baseline]["risk_difference"]
        variance = config_stats[other]["hc3_variance"] + config_stats[baseline]["hc3_variance"]
        p = math.erfc(abs(difference)/math.sqrt(2*variance)) if variance > 1e-15 else None
        lo = hi = 0.0
        for task_id in TASKS:
            for config_id, sign_config in [(other, 1), (baseline, -1)]:
                for condition, sign_condition in [("C1", 1), ("C0", -1)]:
                    group = cells[(task_id, config_id, condition)]
                    interval = exact_binomial(sum(r["primary_pass"] for r in group), 30, .05/(3*32))
                    sign = sign_config*sign_condition
                    lo += (interval[0] if sign == 1 else -interval[1])/8
                    hi += (interval[1] if sign == 1 else -interval[0])/8
        secondary[other] = {"baseline": baseline, "instruction_effect_change": difference,
                            "raw_p": p, "hc3_variance": variance,
                            "bootstrap95": np.quantile(bootstrap_curves[other]-bootstrap_curves[baseline], [.025, .975]).tolist(),
                            "conservative_exact_family95": [lo, hi],
                            "shared_baseline_preserved": True, "asymptotic_test_withheld": p is None}
    for key, value in holm({k: v["raw_p"] for k, v in secondary.items()}).items():
        secondary[key]["holm_p"] = value
    return {"status": "SYNTHETIC PIPELINE CHECK — NOT MODEL RESULTS" if True in synthetic else "main-study analysis",
            "synthetic_data": True in synthetic, "programs": len(observed), "programs_per_cell": 30,
            "fixed_tasks": 8, "bootstrap_resamples": bootstraps, "seed": seed,
            "primary_family_size": 7, "secondary_family_size": 3,
            "failure_priority": list(PRIORITY),
            "primary": primary, "secondary": secondary, "configuration_estimates": config_stats,
            "cells": cell_report, "failure_reconciliation": failure_report, "per_scenario": scenario_report,
            "limits": ["fixed tasks; no random-task population inference", "nominal bootstrap intervals are approximate",
                       "separate primary and secondary multiplicity families", "uncertain results do not establish equivalence"]}


def synthetic_demo():
    rows = []
    rng = np.random.default_rng(20261019)
    for slot in allocation()[0]:
        task_id = slot["task"]
        functional = bool(rng.random() < .8)
        overall = functional and bool(rng.random() < (.65 if slot["condition"] == "C1" else .45))
        checks = []
        failed = False
        for scenario in sorted(scenarios(task_id), key=lambda s: not is_functional(s)):
            if not is_functional(scenario) and not functional:
                break
            passes = overall or (is_functional(scenario) and functional)
            if not overall and not failed and (is_functional(scenario) != functional):
                passes = False
                failed = True
            elif not overall and functional:
                passes = False
            checks.append({"scenario": scenario, "pass": bool(passes), "notes": [], "responses": []})
        rows.append({"synthetic_data": True, "task": task_id, "condition": slot["condition"],
                     "deadline_s": 1, "metadata": slot, "clean_qualified": functional,
                     "primary_pass": bool(overall), "observations": checks,
                     "source_sha256": hashlib.sha256(("SYNTHETIC:"+slot["artifact_id"]).encode()).hexdigest()})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--synthetic-demo", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstraps", type=int, default=20000)
    args = parser.parse_args()
    if args.synthetic_demo == bool(args.input):
        parser.error("choose exactly one of --input or --synthetic-demo")
    rows = synthetic_demo() if args.synthetic_demo else [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    result = summarize(rows, bootstraps=args.bootstraps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ["status", "synthetic_data", "programs", "primary_family_size", "secondary_family_size"]}))


if __name__ == "__main__":
    main()
