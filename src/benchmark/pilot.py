from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from benchmark.artifact_runner import evaluate
from benchmark.paths import resolve_data_path
from benchmark.scenarios import T1_SCENARIOS, T4_SCENARIOS


def _expected_fault_count(task: str) -> int:
    scenarios = T1_SCENARIOS if task == "T1" else T4_SCENARIOS
    return len(scenarios) - 1


def _metric_block(manifests: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
    present = [row for row in manifests if row["status"] in {"evaluated", "evaluation_error"}]
    qualified = {row["artifact_id"] for row in present if row.get("clean_qualified")}
    fault_rows = [row for row in observations if row["scenario"] != "clean" and row["artifact_id"] in qualified]

    by_artifact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fault_rows:
        by_artifact[row["artifact_id"]].append(row)

    application_passes = 0
    for artifact_id in qualified:
        artifact_rows = by_artifact[artifact_id]
        task = next(row["task"] for row in present if row["artifact_id"] == artifact_id)
        if len(artifact_rows) == _expected_fault_count(task) and all(
            meets_probe_oracle_dict(row) for row in artifact_rows
        ):
            application_passes += 1

    all_probe_rows = [row for row in observations if row["artifact_id"] in {item["artifact_id"] for item in present}]
    return {
        "generated_artifacts": len(present),
        "clean_qualified_artifacts": len(qualified),
        "CCR": len(qualified) / len(present) if present else None,
        "SRR": (
            sum(row["outcome_class"] == "resilient_success" for row in fault_rows) / len(fault_rows)
            if fault_rows else None
        ),
        "APR": application_passes / len(qualified) if qualified else None,
        "mean_retry_amplification_factor": (
            sum(row["retry_amplification_factor"] for row in all_probe_rows) / len(all_probe_rows)
            if all_probe_rows else None
        ),
        "duplicate_side_effects": sum(row["duplicate_side_effects"] for row in all_probe_rows),
        "state_consistency_failures": sum(
            row["task"] == "T4" and row["outcome_class"] == "unsafe_failure" for row in all_probe_rows
        ),
    }


def meets_probe_oracle_dict(row: dict[str, Any]) -> bool:
    if (row["task"], row["scenario"]) in {
        ("T1", "persistent_503"),
        ("T1", "timeout"),
        ("T1", "rate_limit"),
        ("T1", "malformed_200"),
        ("T4", "persistent_503"),
        ("T4", "rate_limit"),
        ("T4", "malformed_200"),
    }:
        return row["outcome_class"] in {"resilient_success", "safe_failure"}
    return row["outcome_class"] == "resilient_success"


def summarize_pilot(
    plan: dict[str, Any], manifests: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    cells: dict[str, dict[str, Any]] = {}
    for model_key in plan["models"]:
        for condition in ("C0", "C1"):
            ids = {
                slot["artifact_id"]
                for slot in plan["slots"]
                if slot["model"] == model_key and slot["condition"] == condition
            }
            cell_manifests = [row for row in manifests if row["artifact_id"] in ids]
            cell_observations = [row for row in observations if row["artifact_id"] in ids]
            cells[f"{model_key}:{condition}"] = _metric_block(cell_manifests, cell_observations)

    status_counts: dict[str, int] = defaultdict(int)
    for row in manifests:
        status_counts[row["status"]] += 1
    contrasts = {}
    for model_key in plan["models"]:
        c0 = cells[f"{model_key}:C0"]
        c1 = cells[f"{model_key}:C1"]
        contrasts[model_key] = {
            f"delta_{metric}": c1[metric] - c0[metric]
            if c1[metric] is not None and c0[metric] is not None
            else None
            for metric in ("CCR", "SRR", "APR")
        }
    return {
        "protocol_version": plan["protocol_version"],
        "evaluator_version": "0.4.2",
        "generation_complete": status_counts.get("missing", 0) == 0,
        "planned_artifacts": len(plan["slots"]),
        "pilot_complete": status_counts.get("evaluated", 0) == len(plan["slots"]),
        "status_counts": dict(sorted(status_counts.items())),
        "overall": _metric_block(manifests, observations),
        "cells": cells,
        "condition_contrasts": contrasts,
        "metric_definitions": {
            "CCR": "clean-qualified artifacts / generated artifacts; import and contract failures remain in the denominator",
            "SRR": "resilient-success fault probes / executed fault probes among clean-qualified artifacts",
            "APR": "clean-qualified artifacts satisfying every task-specific probe oracle / clean-qualified artifacts",
            "mean_retry_amplification_factor": "mean downstream attempts per logical operation across executed probes",
            "duplicate_side_effects": "external effects beyond the first effect for each logical operation",
            "state_consistency_failures": "T4 probes classified as unsafe failures",
        },
    }


async def run_pilot(plan: dict[str, Any], artifacts_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifests: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for slot in plan["slots"]:
        model = plan["models"][slot["model"]]
        base = {
            **slot,
            "model_provider": model["provider"],
            "model_family": model["family"],
            "planned_model_id": model["model_id"],
        }
        directory = artifacts_root / slot["artifact_id"]
        if not directory.is_dir():
            manifests.append({**base, "status": "missing", "clean_qualified": False, "probes": 0})
            continue
        try:
            metadata, rows = await evaluate(directory)
            for field in ("artifact_id", "task", "condition", "generation_index"):
                if metadata[field] != slot[field]:
                    raise ValueError(
                        f"metadata {field}={metadata[field]!r} does not match plan value {slot[field]!r}"
                    )
            manifests.append(
                {**base, "status": "evaluated", "clean_qualified": metadata["clean_qualified"], "probes": len(rows)}
            )
            observations.extend({**metadata, **row.to_dict()} for row in rows)
        except Exception as exc:
            manifests.append(
                {
                    **base,
                    "status": "evaluation_error",
                    "clean_qualified": False,
                    "probes": 0,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
    return manifests, observations


def _jsonl(rows: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _csv(rows: list[dict[str, Any]], fields: list[str]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field: json.dumps(row[field], sort_keys=True)
                if field in row and isinstance(row[field], (dict, list))
                else row.get(field)
                for field in fields
            }
        )
    return stream.getvalue()


def _format_metric(value: Any) -> str:
    return "—" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def render_report(summary: dict[str, Any]) -> str:
    overall = summary["overall"]
    status = "complete" if summary["pilot_complete"] else (
        "all artifacts present; construction/evaluation errors recorded"
        if summary["generation_complete"] else "incomplete: artifacts missing"
    )
    rows = [
        "# DepFailBench Pilot Report",
        "",
        f"**Protocol:** v{summary['protocol_version']}  ",
        f"**Evaluator:** v{summary['evaluator_version']}  ",
        f"**Generation complete:** {summary['generation_complete']}  ",
        f"**Status:** {status}  ",
        f"**Planned artifacts:** {summary['planned_artifacts']}  ",
        f"**Artifact statuses:** `{json.dumps(summary['status_counts'], sort_keys=True)}`",
        "",
        "## Overall metrics",
        "",
        "| CCR | SRR | APR | Mean retry amplification | Duplicate side effects | State-consistency failures |",
        "|---:|---:|---:|---:|---:|---:|",
        "| " + " | ".join(
            _format_metric(overall[key])
            for key in (
                "CCR",
                "SRR",
                "APR",
                "mean_retry_amplification_factor",
                "duplicate_side_effects",
                "state_consistency_failures",
            )
        ) + " |",
        "",
        "## Condition-by-model cells",
        "",
        "| Cell | Generated | Qualified | CCR | SRR | APR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cell, metrics in summary["cells"].items():
        rows.append(
            f"| `{cell}` | {metrics['generated_artifacts']} | {metrics['clean_qualified_artifacts']} | "
            f"{_format_metric(metrics['CCR'])} | {_format_metric(metrics['SRR'])} | {_format_metric(metrics['APR'])} |"
        )
    rows.extend(
        [
            "",
            "## C1 − C0 descriptive contrasts",
            "",
            "| Model | ΔCCR | ΔSRR | ΔAPR |",
            "|---|---:|---:|---:|",
        ]
    )
    for model, contrast in summary["condition_contrasts"].items():
        rows.append(
            f"| `{model}` | {_format_metric(contrast['delta_CCR'])} | "
            f"{_format_metric(contrast['delta_SRR'])} | {_format_metric(contrast['delta_APR'])} |"
        )
    rows.extend(
        [
            "",
            "## Interpretation guardrail",
            "",
            "C0 is a functional-only condition. Its fault-probe outcomes characterize operational behavior; they do not imply violation of an undisclosed requirement. C1 explicitly requests resilience behavior. Condition effects are interpreted within each model family.",
            "",
        ]
    )
    if not summary["pilot_complete"]:
        rows.extend(
            [
                "## Completion gate",
                "",
                "Evaluation is incomplete: inspect the manifest for missing artifacts or construction/evaluation errors. Generation completeness is reported separately. Preserve failed generated artifacts; do not repair or replace them to improve scores.",
                "",
            ]
        )
    return "\n".join(rows)


async def execute(plan_path: Path, artifacts_root: Path, output_dir: Path) -> dict[str, Any]:
    plan = json.loads(resolve_data_path(plan_path).read_text())
    manifests, observations = await run_pilot(plan, artifacts_root)
    summary = summarize_pilot(plan, manifests, observations)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "artifact_manifest.jsonl").write_text(_jsonl(manifests))
    (output_dir / "observations.jsonl").write_text(_jsonl(observations))
    (output_dir / "observations.csv").write_text(
        _csv(
            observations,
            [
                "artifact_id",
                "task",
                "condition",
                "model_provider",
                "model_family",
                "model_version",
                "generation_index",
                "scenario",
                "outcome_class",
                "response_status",
                "response_json",
                "latency_s",
                "attempts",
                "deadline_violated",
                "unhandled_exception",
                "side_effects",
                "final_state",
                "retry_amplification_factor",
                "duplicate_side_effects",
                "notes",
            ],
        )
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (output_dir / "pilot_report.md").write_text(render_report(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the frozen 16-artifact DepFailBench pilot.")
    parser.add_argument("--plan", type=Path, default=Path("generation_plan.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/pilot"))
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    summary = asyncio.run(execute(args.plan, args.artifacts, args.output_dir))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["pilot_complete"] and not args.allow_incomplete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
