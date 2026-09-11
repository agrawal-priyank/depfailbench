from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from benchmark.artifact_runner import evaluate
from benchmark.generate import generate_slot, validate_provider_access
from benchmark.metrics import summarize
from benchmark.paths import resolve_data_path
from benchmark.pilot import execute as execute_pilot
from benchmark.runner import run_matrix


def _add_common_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", type=Path, default=Path("generation_plan.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="depfailbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-references", help="validate deterministic control fixtures")
    validate.add_argument("--repetitions", type=int, default=3)
    validate.add_argument("--output", type=Path, default=Path("results/reference_validation.jsonl"))

    generate = subparsers.add_parser("generate", help="preview or execute the frozen generation plan")
    _add_common_plan_arguments(generate)
    generate.add_argument("--slot", action="append", help="artifact ID; repeat to select multiple")
    generate.add_argument("--execute", action="store_true")

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate one generated artifact")
    evaluate_parser.add_argument("artifact", type=Path)
    evaluate_parser.add_argument("--output", type=Path)

    pilot = subparsers.add_parser("pilot", help="evaluate all 16 planned pilot artifacts")
    _add_common_plan_arguments(pilot)
    pilot.add_argument("--output-dir", type=Path, default=Path("results/pilot"))
    pilot.add_argument("--allow-incomplete", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "validate-references":
        rows = asyncio.run(run_matrix(args.repetitions))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(row.to_dict(), sort_keys=True) + "\n" for row in rows))
        print(json.dumps(summarize(rows), indent=2, sort_keys=True))
        return

    if args.command == "generate":
        plan = json.loads(resolve_data_path(args.plan).read_text())
        selected = [slot for slot in plan["slots"] if not args.slot or slot["artifact_id"] in args.slot]
        if args.slot and len(selected) != len(set(args.slot)):
            raise SystemExit("one or more requested artifact IDs are absent from the plan")
        if not args.execute:
            print(json.dumps({"mode": "dry-run", "artifacts": [s["artifact_id"] for s in selected]}, indent=2))
            return
        validate_provider_access(plan, selected)
        for slot in selected:
            print(generate_slot(plan, slot, args.artifacts))
        return

    if args.command == "evaluate":
        metadata, rows = asyncio.run(evaluate(args.artifact))
        output = args.output or args.artifact / "observations.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "".join(json.dumps({**metadata, **row.to_dict()}, sort_keys=True) + "\n" for row in rows)
        )
        print(json.dumps({"output": str(output), "clean_qualified": metadata["clean_qualified"], "probes": len(rows)}))
        return

    summary = asyncio.run(execute_pilot(args.plan, args.artifacts, args.output_dir))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["pilot_complete"] and not args.allow_incomplete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
