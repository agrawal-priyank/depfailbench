"""Local-only expanded-study validation and saved-program evaluation."""

import argparse
from dataclasses import asdict
import importlib.metadata
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

from .contracts import Settings, TASKS, scenarios
from .evaluate import evaluate, probe
from .planning import check, write_plan


def source_manifest():
    directory = Path(__file__).resolve().parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob("*.py"))}


def behavior_signature(row):
    return json.dumps({"pass": row["pass"], "outcome": row["outcome_class"],
                       "responses": [{"status": r["status"], "success_body": r["body"] if r["status"] == 200 else None}
                                     for r in row.get("responses", [])],
                       "effects": (row.get("dependency") or {}).get("effects", []),
                       "objects": (row.get("dependency") or {}).get("objects", {}),
                       "preferences": (row.get("dependency") or {}).get("preferences", {}),
                       "application_state": row.get("application_state", {}),
                       "watchdog": row.get("watchdog_intervened", False)}, sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--output", type=Path)
    validate = sub.add_parser("validate-references")
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--deadlines", type=float, nargs="+", default=[1, 2, 5])
    validate.add_argument("--repeats", type=int, default=1)
    validate.add_argument("--task", choices=TASKS, action="append")
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("artifact", type=Path)
    evaluate_parser.add_argument("--deadline", type=float, default=1)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        result = write_plan(args.output) if args.output else check()
    elif args.command == "validate-references":
        args.output.mkdir(parents=True, exist_ok=True)
        starting_manifest = source_manifest()
        rows = []
        with (args.output / "reference_observations.jsonl").open("w") as handle:
            for deadline in args.deadlines:
                for repeat in range(1, args.repeats + 1):
                    for task in args.task or TASKS:
                        for scenario in scenarios(task):
                            row = probe(task, scenario, settings=Settings(deadline_s=deadline))
                            row["repeat"] = repeat
                            rows.append(row)
                            handle.write(json.dumps(row) + "\n")
                            handle.flush()
                        print(json.dumps({"task": task, "deadline_s": deadline, "repeat": repeat,
                                          "cumulative_probes": len(rows), "failed": sum(not r["pass"] for r in rows)}), flush=True)
        fingerprints = {}
        for row in rows:
            coordinate = f"{row['task']}:{row['scenario']}:{row['deadline_s']}"
            fingerprints.setdefault(coordinate, set()).add(behavior_signature(row))
        disagreements = [key for key, values in fingerprints.items() if len(values) > 1]
        source_unchanged = starting_manifest == source_manifest()
        result = {"passed": all(r["pass"] for r in rows) and not disagreements and source_unchanged,
                  "validation_kind": "hand_written_reference_checks_not_model_outputs",
                  "probe_count": len(rows), "reproducibility_disagreements": disagreements,
                  "source_manifest": starting_manifest, "source_unchanged_during_run": source_unchanged,
                  "failures": [{"task": r["task"], "scenario": r["scenario"], "deadline_s": r["deadline_s"],
                                "repeat": r["repeat"], "notes": r["notes"]} for r in rows if not r["pass"]],
                  "environment": {name: importlib.metadata.version(name) for name in
                                  ("fastapi", "starlette", "httpx", "pydantic", "uvicorn", "pytest")},
                  "python": sys.version, "platform": platform.platform(),
                  "monotonic_clock_resolution_s": time.get_clock_info("monotonic").resolution,
                  "model_api_calls": 0, "settings": asdict(Settings())}
        (args.output / "reference_summary.json").write_text(json.dumps(result, indent=2) + "\n")
    else:
        metadata = json.loads((args.artifact / "metadata.json").read_text())
        result = evaluate(metadata["task"], metadata["condition"], source=args.artifact / "app.py",
                          settings=Settings(deadline_s=args.deadline), metadata=metadata)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    if args.command == "validate-references" and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
