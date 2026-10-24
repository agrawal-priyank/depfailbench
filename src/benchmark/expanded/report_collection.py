"""Publish repeat-1 tables and descriptive deadline sensitivity from saved data."""

import argparse
from collections import Counter, defaultdict
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np

from .collect import CollectionError, audit_collection, record_path, save_new, verify_record
from .contracts import TASKS, scenarios
from .failure_reporting import PRIORITY, failure_flags
from .planning import assets_root


def analysis_module(root=None):
    spec = importlib.util.spec_from_file_location("depfailbench_expanded_analysis", assets_root(root) / "analysis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def slim_result(envelope, *, disagreement, record_relative):
    result = envelope["result"]
    row = {k: result[k] for k in ("task", "condition", "deadline_s", "clean_qualified", "primary_pass", "metadata")}
    row.update(source_sha256=envelope["source_sha256"], synthetic_data=envelope["synthetic_data"],
               evaluation_repeat=1, reproducibility_disagreement=disagreement,
               raw_record_path=record_relative, raw_record_sha256=envelope["record_sha256"])
    for k in ("generation_failure", "integrity_error"):
        if k in result:
            row[k] = result[k]
    row["observations"] = [{**{k: o[k] for k in ("scenario", "pass")},
        "outcome_class": o.get("outcome_class"), "notes": o.get("notes", []),
        "watchdog_intervened": o.get("watchdog_intervened", False),
        "startup_error": o.get("startup_error"), "startup_s": o.get("startup_s"),
        "responses": [{"status": r["status"], "wall_latency_s": r.get("wall_latency_s")} for r in o.get("responses", [])]}
        for o in result.get("observations", [])]
    return row


def tables(rows, *, root=None, bootstraps=20000):
    """Descriptive tables use one binary outcome per program per deadline."""
    analysis = analysis_module(root)
    design = json.loads((assets_root(root) / "study.json").read_text())
    configs = {c["id"]: c for c in design["configurations"]}
    cells, by_program = defaultdict(list), defaultdict(dict)
    programs = []
    for row in rows:
        if row.get("evaluation_repeat") != 1:
            raise CollectionError("reporting accepts only prespecified repeat 1")
        metadata = row["metadata"]
        if metadata.get("task") != row["task"] or metadata.get("condition") != row["condition"]:
            raise CollectionError("reporting coordinates differ from artifact metadata")
        identity, deadline = metadata["artifact_id"], row["deadline_s"]
        if deadline not in (1, 2, 5) or deadline in by_program[identity]:
            raise CollectionError("unexpected or duplicated program/deadline")
        by_program[identity][deadline] = row
        cells[(deadline, row["task"], metadata["configuration_id"], row["condition"])].append(row)
        flags = failure_flags(row)
        latencies = [r["wall_latency_s"] for o in row["observations"] for r in o["responses"] if r.get("wall_latency_s") is not None]
        startup = [o["startup_s"] for o in row["observations"] if o.get("startup_s") is not None]
        programs.append({"artifact_id": identity, "cohort": metadata["cohort"], "task": row["task"],
            "configuration": metadata["configuration_id"], "requested_model": metadata["model_id"],
            "resolved_model": metadata.get("resolved_model_id"), "condition": row["condition"],
            "deadline_s": deadline, "repeat": 1, "source_sha256": row["source_sha256"],
            "generation_status": metadata.get("generation_status"), "functional_qualified": row["clean_qualified"],
            "all_pass": row["primary_pass"], "declared_checks": len(scenarios(row["task"])),
            "executed_checks": len(row["observations"]), "max_startup_s": max(startup, default=None),
            "max_public_wall_latency_s": max(latencies, default=None),
            "exclusive_failure_category": next((p for p in PRIORITY if p in flags), None),
            "overlapping_failure_flags": sorted(flags), "reproducibility_disagreement": row.get("reproducibility_disagreement", False),
            "raw_record_path": row.get("raw_record_path"), "synthetic_data": row.get("synthetic_data", False)})
    for identity, deadlines in by_program.items():
        if set(deadlines) != {1, 2, 5}:
            raise CollectionError("missing same-program deadline result")
        if len({r["source_sha256"] for r in deadlines.values()}) != 1 or len({json.dumps(r["metadata"], sort_keys=True) for r in deadlines.values()}) != 1:
            raise CollectionError("program source or generation metadata differs across deadlines")
    cell_rows, scenario_rows, failure_rows = [], [], []
    for (deadline, task, config, condition), group in sorted(cells.items()):
        prefix = {"deadline_s": deadline, "task": task, "configuration": config, "condition": condition}
        n, k = len(group), sum(r["primary_pass"] for r in group)
        cell_rows.append({**prefix, "generated_n": n, "passed_n": k, "rate": k/n,
                          "wilson95": analysis.wilson(k, n),
                          "functional_qualified_n": sum(r["clean_qualified"] for r in group)})
        disjoint, overlap = Counter(), Counter()
        for row in group:
            flags = failure_flags(row)
            if flags:
                disjoint[next(p for p in PRIORITY if p in flags)] += 1
                overlap.update(flags)
        if sum(disjoint.values()) != n-k:
            raise CollectionError("program failure totals do not reconcile")
        failure_rows.append({**prefix, "generated_n": n, "failed_programs": n-k,
                             "disjoint_priority_counts": dict(disjoint), "overlapping_reason_counts": dict(overlap)})
        for scenario in scenarios(task):
            reached = [o for r in group for o in r["observations"] if o["scenario"] == scenario]
            passed = sum(o["pass"] for o in reached)
            scenario_rows.append({**prefix, "scenario": scenario, "generated_n": n, "reached_n": len(reached),
                "not_reached_n": n-len(reached), "passed_n": passed,
                "rate_among_reached": passed/len(reached) if reached else None,
                "rate_all_generated": passed/n})
    transitions = defaultdict(Counter)
    for identity, pair in by_program.items():
        metadata = pair[1]["metadata"]
        for larger in (2, 5):
            transitions[(metadata["task"], metadata["configuration_id"], metadata["condition"], larger)][
                (pair[1]["primary_pass"], pair[larger]["primary_pass"])] += 1
    paired = []
    for (task, config, condition, larger), counts in sorted(transitions.items()):
        n = sum(counts.values())
        paired.append({"task": task, "configuration": config, "condition": condition,
            "from_deadline_s": 1, "to_deadline_s": larger, "same_saved_programs_n": n,
            "failed_both": counts[(False, False)], "improved": counts[(False, True)],
            "worsened": counts[(True, False)], "passed_both": counts[(True, True)],
            "pass_rate_change": (counts[(False, True)]-counts[(True, False)])/n,
            "inference": "descriptive paired outcomes; no confirmatory deadline test"})
    aggregate = []
    rng = np.random.default_rng(design["seed"])
    for deadline in (1, 2, 5):
        for config in configs:
            if not all((deadline, t, config, c) in cells for t in TASKS for c in ("C0", "C1")):
                continue
            estimate = lower = upper = 0.0
            draws = np.zeros(bootstraps)
            boundary = False
            for task in TASKS:
                for condition, sign in (("C0", -1), ("C1", 1)):
                    group = cells[(deadline, task, config, condition)]
                    n, k = len(group), sum(r["primary_pass"] for r in group)
                    estimate += sign * k/n/8
                    draws += sign * rng.binomial(n, k/n, size=bootstraps)/n/8
                    lo, hi = analysis.exact_binomial(k, n, .05/16)
                    lower += (lo if sign == 1 else -hi)/8
                    upper += (hi if sign == 1 else -lo)/8
                    boundary |= k in {0, n}
            aggregate.append({"deadline_s": deadline, "configuration": config, "c1_minus_c0": estimate,
                "nominal_bootstrap95": np.quantile(draws, [.025, .975]).tolist(),
                "conservative_exact95": [lower, upper], "boundary_cells_present": boundary,
                "inference": "descriptive within-deadline estimate; intervals do not test cross-deadline changes"})
    return {"programs": programs, "cells": cell_rows, "scenarios": scenario_rows,
            "failures": failure_rows, "paired_deadlines": paired, "aggregate_deadlines": aggregate}


def write_csv(path, rows):
    with Path(path).open("x", newline="", encoding="utf-8") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def export(output, destination, *, root=None, bootstraps=20000):
    output, destination = Path(output), Path(destination)
    summary = audit_collection(output)
    manifest = json.loads((output / "collection_manifest.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    disagreements = {(d["artifact_id"], d["deadline_s"]) for d in summary["reproducibility_disagreements"]}
    rows = []
    for identity in manifest["inputs"]:
        for deadline in manifest["deadlines"]:
            path = record_path(output, identity, deadline, 1)
            envelope = json.loads(path.read_text())
            verify_record(envelope, manifest, identity, deadline, 1)
            rows.append(slim_result(envelope, disagreement=(identity, deadline) in disagreements,
                                    record_relative=str(path.relative_to(output))))
    data = tables(rows, root=root, bootstraps=bootstraps)
    for name, values in data.items():
        write_csv(destination / f"{name}.csv", values)
    for deadline in (1, 2, 5):
        with (destination / f"deadline_{deadline}_repeat_1.jsonl").open("x") as handle:
            for row in rows:
                if row["deadline_s"] == deadline:
                    handle.write(json.dumps(row, allow_nan=False) + "\n")
    primary_status = "withheld: incomplete main cohort, validation cohort or repeat disagreement"
    if manifest["cohort"] == "main" and not manifest["diagnostic_subset"] and not disagreements:
        primary = analysis_module(root).summarize([r for r in rows if r["deadline_s"] == 1], bootstraps=bootstraps, root=root)
        save_new(destination / "primary_analysis.json", primary)
        primary_status = primary["status"]
    report = {"status": "SYNTHETIC COLLECTION EXPORT — NOT MODEL RESULTS" if summary["synthetic_data"] else "saved-program collection export",
        "synthetic_data": summary["synthetic_data"], "cohort": manifest["cohort"],
        "distinct_programs": summary["programs"], "deadline_rows_repeat_1": len(rows),
        "evaluation_records_including_audit_repeats": summary["evaluation_records"],
        "selected_repeat": 1, "run_fingerprint": summary["run_fingerprint"],
        "reproducibility_disagreements": summary["reproducibility_disagreements"],
        "literal_trace_disagreements": summary["literal_trace_disagreements"],
        "permitted_internal_identifier_variations": summary["permitted_internal_identifier_variations"],
        "repeat_comparison_policy": summary["repeat_comparison_policy"],
        "primary_analysis_status": primary_status, "confirmatory_ready": summary["confirmatory_ready"],
        "bootstrap_resamples": bootstraps, "environment": manifest["environment"],
        "table_rows": {k: len(v) for k, v in data.items()},
        "failure_priority": list(PRIORITY), "raw_records_preserved_at": str(output.resolve()),
        "denominator_note": "one program per deadline; repeats 2/3 audit reproducibility and do not increase n",
        "model_api_calls": 0}
    save_new(destination / "export_summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstraps", type=int, default=20000)
    args = parser.parse_args()
    result = export(args.collection, args.output, bootstraps=args.bootstraps)
    print(json.dumps({k: v for k, v in result.items() if k != "environment"}, indent=2))


if __name__ == "__main__":
    main()
