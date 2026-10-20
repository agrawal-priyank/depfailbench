"""Local collection controls and synthetic reporting; never model generations."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import random

from .collect import collect, digest, save_new
from .contracts import TASKS, is_functional
from .planning import allocation, assets_root, prompt


def write_control(directory, slot, *, source=None, status="completed", root=None):
    root, directory = assets_root(root), Path(directory)
    config = next(c for c in json.loads((root / "study.json").read_text())["configurations"] if c["id"] == slot["configuration_id"])
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "prompt.txt").write_text(prompt(slot["task"], slot["condition"], root))
    if source is not None:
        (directory / "app.py").write_text(source)
    metadata = {**slot, "generation_status": status, "source_origin": "hand_written_software_control",
                "synthetic_data": True, "simulation_only": True,
                "source_sha256": digest(directory / "app.py") if source is not None else None,
                "generation_settings": config["generation_settings"], "output_limit_semantics": config["output_limit_semantics"]}
    save_new(directory / "metadata.json", metadata)
    save_new(directory / "configuration.json", config)
    save_new(directory / "provenance.json", {"simulation_only": True, "study_sha256": digest(root / "study.json"),
        "scaffold_sha256": digest(root / "scaffold.py"), "task_manifest_sha256": digest(root / "task_contracts.json"),
        "dependency_lock_sha256": digest(root.parent / "requirements.lock")})
    return metadata


def reference_controls(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    controls, expected = [], {}
    validation = allocation()[1]
    for task in TASKS:
        slot = next(s for s in validation if s["task"] == task and s["configuration_id"] == "gpt_6_1_sol" and s["condition"] == "C0")
        source = ("from benchmark.expanded.reference import create_reference\n"
                  "def create_app(transport, settings=None):\n"
                  f"    return create_reference({task!r}, transport, settings)\n")
        write_control(output / "artifacts" / slot["artifact_id"], slot, source=source)
        controls.append(slot["artifact_id"])
        expected[slot["artifact_id"]] = True
    for config, condition, source, status in (("gpt_6_1_sol", "C1", "def broken(\n", "completed"),
                                             ("gpt_6_luna", "C0", None, "no_code")):
        slot = next(s for s in validation if s["task"] == "E1" and s["configuration_id"] == config and s["condition"] == condition)
        write_control(output / "artifacts" / slot["artifact_id"], slot, source=source, status=status)
        controls.append(slot["artifact_id"])
        expected[slot["artifact_id"]] = False
    last = [0]
    def progress(row):
        if row["completed_jobs"] - last[0] >= 5:
            print(json.dumps(row), flush=True)
            last[0] = row["completed_jobs"]
    report = collect(output / "artifacts", output / "collection", cohort="validation", artifact_ids=controls, progress=progress)
    passed = not report["reproducibility_disagreements"] and all(r["primary_pass"] == expected[r["artifact_id"]] for r in report["selected_outcomes"])
    result = {"status": "HAND-WRITTEN COLLECTION CONTROLS — NOT MODEL RESULTS", "synthetic_data": True,
              "passed": passed, "programs": 10, "correct_reference_programs": 8,
              "negative_controls": ["startup_syntax_error", "returned_no_code"],
              "evaluation_records": report["evaluation_records"], "executed_probes": report["executed_probes_all_repeats"],
              "reproducibility_disagreements": report["reproducibility_disagreements"], "model_api_calls": 0}
    save_new(output / "control_summary.json", result)
    return result


def synthetic_deadline_rows(root=None):
    from .report_collection import analysis_module
    analysis = analysis_module(root)
    rng = random.Random(20261019)
    rows = []
    for original in analysis.synthetic_demo():
        for deadline in (1, 2, 5):
            row = deepcopy(original)
            row.update(deadline_s=deadline, evaluation_repeat=1, reproducibility_disagreement=False)
            row["metadata"] = {**row["metadata"], "generation_status": "completed", "synthetic_data": True}
            if deadline > 1 and row["clean_qualified"]:
                if row["primary_pass"] and rng.random() < .025:
                    row["primary_pass"] = False
                    next(o for o in row["observations"] if not is_functional(o["scenario"]))["pass"] = False
                elif not row["primary_pass"] and rng.random() < .12 * (deadline == 2) + .24 * (deadline == 5):
                    row["primary_pass"] = True
                    for o in row["observations"]:
                        o["pass"] = True
            for o in row["observations"]:
                o.setdefault("outcome_class", "resilient_success" if o["pass"] else "availability_failure")
            rows.append(row)
    return rows


def synthetic_reporting(output, bootstraps=20000):
    from .report_collection import analysis_module, tables, write_csv
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = synthetic_deadline_rows()
    data = tables(rows, bootstraps=bootstraps)
    for key, values in data.items():
        write_csv(output / f"{key}.csv", values)
    primary = analysis_module().summarize([r for r in rows if r["deadline_s"] == 1], bootstraps=bootstraps)
    save_new(output / "primary_analysis.json", primary)
    result = {"status": "SYNTHETIC THREE-DEADLINE REPORTING — NOT MODEL RESULTS", "synthetic_data": True,
        "distinct_programs": 4800, "repeat_1_deadline_rows": len(rows), "primary_family_size": primary["primary_family_size"],
        "secondary_family_size": primary["secondary_family_size"], "table_rows": {k: len(v) for k, v in data.items()},
        "bootstrap_resamples": bootstraps, "model_api_calls": 0,
        "passed": len(rows) == 14400 and len(data["cells"]) == 480 and len(data["paired_deadlines"]) == 320 and
                  all(sum(r["disjoint_priority_counts"].values()) == r["failed_programs"] for r in data["failures"]) and
                  any(r["worsened"] for r in data["paired_deadlines"]) and any(r["improved"] for r in data["paired_deadlines"])}
    save_new(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("reference-controls", "synthetic-reporting"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstraps", type=int, default=20000)
    args = parser.parse_args()
    result = reference_controls(args.output) if args.mode == "reference-controls" else synthetic_reporting(args.output, args.bootstraps)
    print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
