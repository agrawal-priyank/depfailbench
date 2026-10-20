"""Evaluate the immutable, excluded 16-program Anthropic validation batch.

This wrapper has no provider/generation imports, API requests or credentials.
The original study assets are unchanged. One explicitly hashed oracle correction
accepts the status representations permitted by the unchanged action-task text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from benchmark.expanded.collect import (
    artifact_manifest, collect, implementation_manifest, save_new,
)
from benchmark.expanded.planning import allocation, assets_root, digest


ARCHIVE_SHA256 = "064fa01b5c82b2065ee02b1d66a11ad9ab84f27bd5993ede5a6e7d9c4027fe9e"
SOURCE_RUN_ID = 39458106201
SOURCE_ARTIFACT_ID = 12281573442
MEASUREMENT_AMENDMENT = {
    "file": "implementation/oracles.py",
    "original_sha256": "ea77ea68423b9f8fce7e0ddd5908f8b24f5200603ccaabaa473803f41f325701",
    "evaluation_sha256": "a3c24b3140cbd0a2aa89de20fe05bb585c6bb219b35f6cb821a2fea2c344d064",
    "reason": "Accept keyed status strings or status records as permitted by E5/E6; retain public receipt, external effect and truthful-state checks. Do not impose an undocumented requirement that receipts be duplicated inside status records.",
    "applies_uniformly_to_all_providers_conditions_deadlines": True,
    "generation_inputs_changed": False,
}


def extract_checked(archive, destination):
    """Reject unsafe ZIP members before writing any files."""
    with zipfile.ZipFile(archive) as bundle:
        seen = set()
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                    or str(path) in seen or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError("unsafe or duplicate archive member")
            seen.add(str(path))
        if bundle.testzip() is not None:
            raise ValueError("archive CRC mismatch")
        destination.mkdir(parents=True, exist_ok=False)
        bundle.extractall(destination)


def inputs(output):
    """Require the original generation plan, core and actual saved sources."""
    root = assets_root()
    evidence = Path(output) / "original" / "anthropic_api_validation"
    saved_plan = evidence / "reviewed_plan.json"
    plan = json.loads(saved_plan.read_text())
    if plan != json.loads((root.parent / "scripts/expanded_anthropic_validation_plan.json").read_text()):
        raise ValueError("saved generation plan differs from the reviewed plan")
    for name, expected in plan["snapshot"].items():
        path = (Path(__file__).resolve().parents[1] / "src/benchmark/expanded" / name.removeprefix("implementation/")) if name.startswith("implementation/") else root.parent / name
        if name == MEASUREMENT_AMENDMENT["file"]:
            if expected != MEASUREMENT_AMENDMENT["original_sha256"]:
                raise ValueError("original oracle differs from the documented correction")
            expected = MEASUREMENT_AMENDMENT["evaluation_sha256"]
        if digest(path) != expected:
            raise ValueError(f"original study/core changed: {name}")
    declared = [s for s in allocation(root)[1] if s["provider"] == "Anthropic"]
    if declared != plan["slots"] or len(declared) != 16:
        raise ValueError("expected exactly the original sixteen validation slots")
    artifacts = evidence / "artifacts"
    if {p.name for p in artifacts.iterdir()} != {s["artifact_id"] for s in declared}:
        raise ValueError("missing or unexpected actual validation artifact")
    design = json.loads((root / "study.json").read_text())
    configs = {c["id"]: c for c in design["configurations"]}
    manifests = {s["artifact_id"]: artifact_manifest(artifacts / s["artifact_id"], s, configs[s["configuration_id"]], root) for s in declared}
    if any(m["synthetic_data"] for m in manifests.values()):
        raise ValueError("actual validation cannot use synthetic artifacts")
    return artifacts, declared, manifests


def prepare(archive, output):
    archive, output = Path(archive), Path(output)
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("archive differs from the verified original generation artifact")
    if output.exists():
        raise ValueError("refusing to overwrite an evaluation directory")
    extract_checked(archive, output / "original")
    _, slots, manifests = inputs(output)
    report = {"source_generation_run_id": SOURCE_RUN_ID, "source_artifact_id": SOURCE_ARTIFACT_ID,
        "archive_sha256": ARCHIVE_SHA256, "cohort": "validation", "excluded_from_main": True,
        "measurement_amendment": MEASUREMENT_AMENDMENT,
        "programs": len(slots), "inputs": manifests, "implementation": implementation_manifest(),
        "original_files": {str(p.relative_to(output / "original")): digest(p)
                           for p in sorted((output / "original").rglob("*")) if p.is_file()},
        "model_api_calls": 0}
    save_new(output / "verified_inputs.json", report)
    return report


def evaluate_saved(output):
    # Analysis is optional for ordinary installs and archive/guard checks.
    from benchmark.expanded.report_collection import export

    output = Path(output)
    verified = json.loads((output / "verified_inputs.json").read_text())
    artifacts, slots, manifests = inputs(output)
    original_files = lambda: {str(p.relative_to(output / "original")): digest(p)
                              for p in sorted((output / "original").rglob("*")) if p.is_file()}
    if (verified["archive_sha256"] != ARCHIVE_SHA256 or verified["inputs"] != manifests
            or verified["measurement_amendment"] != MEASUREMENT_AMENDMENT
            or verified["implementation"] != implementation_manifest()
            or verified["original_files"] != original_files()):
        raise ValueError("verified inputs changed before evaluation")
    summary = collect(artifacts, output / "collection", cohort="validation",
        artifact_ids=[s["artifact_id"] for s in slots],
        progress=lambda row: print(json.dumps(row), flush=True))
    if verified["original_files"] != original_files():
        raise ValueError("original evidence changed during evaluation")
    report = export(output / "collection", output / "exports")
    return {"collection": {k: v for k, v in summary.items() if k != "selected_outcomes"},
            "export": report, "model_api_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "evaluate"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        if args.archive is None:
            parser.error("prepare requires --archive")
        report = prepare(args.archive, args.output)
        print(json.dumps({k: v for k, v in report.items() if k not in {"inputs", "original_files", "implementation"}}, indent=2))
    else:
        report = evaluate_saved(args.output)
        save_new(args.output / "evaluation_summary.json", report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
