"""Collect the same saved programs at every declared deadline and repeat.

No generation/provider module is imported. Immutable raw records permit restart;
repeat 1 is selected in advance, and disagreement blocks confirmatory reporting.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import sys
import tempfile
import time

from .contracts import Settings, scenarios
from .evaluate import evaluate
from .planning import allocation, assets_root, check, digest


class CollectionError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def value_hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def save_new(path, value):
    """Atomically publish a complete record; never overwrite existing evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".collect-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)  # Atomic exclusive creation on macOS/Linux.
    finally:
        Path(temporary).unlink(missing_ok=True)


def implementation_manifest():
    return {p.name: digest(p) for p in sorted(Path(__file__).resolve().parent.glob("*.py"))}


def environment():
    return {"python": sys.version, "platform": platform.platform(),
            "machine": platform.machine(), "processor": platform.processor(),
            "packages": {p: importlib.metadata.version(p) for p in
                         ("fastapi", "starlette", "httpx", "pydantic", "uvicorn")},
            "monotonic_clock_resolution_s": time.get_clock_info("monotonic").resolution}


def asset_manifest(root):
    files = [p for folder in (root / "tasks", root / "prompts") for p in folder.iterdir() if p.is_file()]
    files += [root / p for p in ("study.json", "scaffold.py", "task_contracts.json")]
    result = {str(p.relative_to(root)): digest(p) for p in sorted(files)}
    result["../requirements.lock"] = digest(root.parent / "requirements.lock")
    return result


def artifact_manifest(directory, slot, config, root):
    required = ("metadata.json", "prompt.txt", "configuration.json", "provenance.json")
    if any(not (directory / p).is_file() for p in required):
        raise CollectionError(f"missing artifact evidence: {slot['artifact_id']}")
    metadata = json.loads((directory / "metadata.json").read_text())
    if canonical({k: metadata.get(k) for k in slot}) != canonical(slot):
        raise CollectionError("artifact coordinates differ from the declared allocation")
    if canonical(json.loads((directory / "configuration.json").read_text())) != canonical(config):
        raise CollectionError("saved provider configuration differs from the design")
    if canonical(metadata.get("generation_settings")) != canonical(config["generation_settings"]):
        raise CollectionError("metadata generation settings differ from the configuration")
    if metadata.get("output_limit_semantics") != config["output_limit_semantics"]:
        raise CollectionError("output-limit semantics differ from the configuration")
    if (directory / "prompt.txt").read_bytes() != (root / "prompts" / f"{slot['task']}_{slot['condition']}.md").read_bytes():
        raise CollectionError("saved prompt bytes differ from the design")
    if digest(directory / "prompt.txt") != slot["prompt_sha256"]:
        raise CollectionError("prompt hash mismatch")
    provenance = json.loads((directory / "provenance.json").read_text())
    for key, file in (("study_sha256", root / "study.json"), ("scaffold_sha256", root / "scaffold.py"),
                      ("task_manifest_sha256", root / "task_contracts.json"),
                      ("dependency_lock_sha256", root.parent / "requirements.lock")):
        if provenance.get(key) != digest(file):
            raise CollectionError(f"artifact provenance differs: {key}")
    if metadata.get("generation_status") not in {"completed", "truncated", "refused", "incomplete", "no_code"}:
        raise CollectionError("missing or unknown returned-generation status; service-only slots are unfilled")
    source = directory / "app.py"
    source_hash = digest(source) if source.is_file() else None
    if source_hash != metadata.get("source_sha256") or metadata["generation_status"] == "completed" and source_hash is None:
        raise CollectionError("saved source is missing or differs from its recorded hash")
    files = {p: digest(directory / p) for p in required}
    if source_hash is not None:
        files["app.py"] = source_hash
    synthetic = bool(metadata.get("simulation_only") or metadata.get("synthetic_data"))
    if bool(provenance.get("simulation_only")) != synthetic:
        raise CollectionError("simulation provenance and artifact metadata disagree")
    if not synthetic:
        attempts = sorted(directory.glob("attempt_*"))
        if not attempts or any(not all((a / p).is_file() for p in
            ("request.json", "wire_response.bin", "attempt.json", "assembled_response.json")) for a in attempts):
            raise CollectionError("actual artifact is missing raw provider attempt evidence")
        for attempt in attempts:
            files.update({str(p.relative_to(directory)): digest(p) for p in attempt.rglob("*") if p.is_file()})
    return {"files": files, "source_sha256": source_hash, "synthetic_data": synthetic,
            "metadata": metadata}


def record_path(output, identity, deadline, repeat):
    return Path(output) / "records" / identity / f"deadline_{deadline}_repeat_{repeat}.json"


def behavior_signature(result):
    """Compare scientific outputs/state, excluding naturally variable timings."""
    return value_hash({"clean_qualified": result["clean_qualified"], "primary_pass": result["primary_pass"],
        "generation_failure": result.get("generation_failure"), "integrity_error": result.get("integrity_error"),
        "observations": [{"scenario": o["scenario"], "pass": o["pass"], "outcome_class": o.get("outcome_class"),
            "watchdog_intervened": o.get("watchdog_intervened", False),
            "responses": [{"status": r["status"], "successful_body": r.get("body") if r["status"] == 200 else None}
                          for r in o.get("responses", [])],
            "effects": (o.get("dependency") or {}).get("effects", []),
            "objects": (o.get("dependency") or {}).get("objects", {}),
            "preferences": (o.get("dependency") or {}).get("preferences", {}),
            "stock": (o.get("dependency") or {}).get("stock", {}),
            "application_state": o.get("application_state", {})} for o in result.get("observations", [])]})


def validate_result(result, metadata, deadline):
    if (result.get("task"), result.get("condition"), result.get("deadline_s")) != (metadata["task"], metadata["condition"], deadline):
        raise CollectionError("evaluator returned different coordinates")
    if canonical(result.get("metadata")) != canonical(metadata):
        raise CollectionError("evaluator lost or changed artifact metadata")
    if any(type(result.get(k)) is not bool for k in ("clean_qualified", "primary_pass")):
        raise CollectionError("evaluator outcomes are not explicit Booleans")
    if result.get("integrity_error"):
        raise CollectionError("evaluator detected source modification")
    if result.get("source_sha256") != metadata.get("source_sha256"):
        raise CollectionError("evaluation did not use the recorded saved source")
    checks = result.get("observations", [])
    ids = [c["scenario"] for c in checks]
    declared = set(scenarios(metadata["task"]))
    if len(set(ids)) != len(ids) or set(ids) - declared:
        raise CollectionError("unknown or duplicated scenario record")
    if any(type(c.get("pass")) is not bool for c in checks):
        raise CollectionError("probe outcomes must be explicit Booleans")
    if result["clean_qualified"] and set(ids) != declared:
        raise CollectionError("qualified program has missing fault observations")
    derived = bool(result["clean_qualified"] and set(ids) == declared and all(c["pass"] for c in checks)
                   and not result.get("generation_failure"))
    if result["primary_pass"] != derived:
        raise CollectionError("AllPass does not match the recorded probes")


def collect(artifacts, output, *, cohort="main", artifact_ids=None, root=None, progress=None, evaluator=None):
    root, artifacts, output = assets_root(root), Path(artifacts), Path(output)
    check(root)
    design = json.loads((root / "study.json").read_text())
    if cohort not in {"main", "validation"}:
        raise CollectionError("cohort must be main or validation")
    expected = allocation(root)[0 if cohort == "main" else 1]
    requested = set(artifact_ids) if artifact_ids is not None else {s["artifact_id"] for s in expected}
    if not requested or not requested <= {s["artifact_id"] for s in expected}:
        raise CollectionError("empty or unknown diagnostic subset")
    slots = [s for s in expected if s["artifact_id"] in requested]
    available = {p.name for p in artifacts.iterdir() if p.is_dir()}
    if (artifact_ids is None and available != requested) or not requested <= available:
        raise CollectionError("missing or unexpected artifact directories; no denominator reduction")
    configs = {c["id"]: c for c in design["configurations"]}
    inputs = {s["artifact_id"]: artifact_manifest(artifacts / s["artifact_id"], s, configs[s["configuration_id"]], root) for s in slots}
    if len({i["synthetic_data"] for i in inputs.values()}) != 1:
        raise CollectionError("cannot mix synthetic and actual artifacts")
    deadlines = [design["primary_deadline_s"], *design["secondary_deadlines_s"]]
    if deadlines != [1, 2, 5] or design["evaluation_repeats"] != 3:
        raise CollectionError("collector requires the selected 1/2/5-second, three-repeat matrix")
    invariant = {"schema_version": 1, "cohort": cohort, "expected_cohort_programs": len(expected),
        "selected_programs": len(slots), "diagnostic_subset": len(slots) != len(expected),
        "synthetic_data": next(iter(inputs.values()))["synthetic_data"],
        "deadlines": deadlines, "repeats": 3, "selected_repeat": 1, "seed": design["seed"],
        "inputs": inputs, "assets": asset_manifest(root), "implementation": implementation_manifest(),
        "environment": environment(), "settings": asdict(Settings())}
    manifest = {**invariant, "run_fingerprint": value_hash(invariant)}
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "collection_manifest.json"
    if manifest_path.exists():
        if canonical(json.loads(manifest_path.read_text())) != canonical(manifest):
            raise CollectionError("cannot resume with changed inputs, implementation or environment")
    else:
        if any(output.iterdir()):
            raise CollectionError("nonempty output directory has no collection manifest")
        save_new(manifest_path, manifest)
    jobs = [(s, d, r) for s in slots for d in deadlines for r in range(1, 4)]
    random.Random(design["seed"]).shuffle(jobs)
    expected_paths = {record_path(output, s["artifact_id"], d, r) for s, d, r in jobs}
    if set((output / "records").glob("*/*.json")) - expected_paths:
        raise CollectionError("unexpected evaluation records")
    evaluated = 0
    evaluator = evaluator or evaluate
    for index, (slot, deadline, repeat) in enumerate(jobs, 1):
        identity = slot["artifact_id"]
        path = record_path(output, identity, deadline, repeat)
        if implementation_manifest() != manifest["implementation"] or asset_manifest(root) != manifest["assets"]:
            raise CollectionError("measurement implementation/assets changed during collection")
        before = artifact_manifest(artifacts / identity, slot, configs[slot["configuration_id"]], root)
        if canonical(before) != canonical(inputs[identity]):
            raise CollectionError("artifact source or evidence changed during collection")
        if path.exists():
            row = json.loads(path.read_text())
        else:
            result = evaluator(slot["task"], slot["condition"], source=artifacts / identity / "app.py",
                settings=Settings(deadline_s=deadline), metadata=inputs[identity]["metadata"])
            if implementation_manifest() != manifest["implementation"] or asset_manifest(root) != manifest["assets"]:
                raise CollectionError("measurement implementation/assets changed during evaluation")
            after = artifact_manifest(artifacts / identity, slot, configs[slot["configuration_id"]], root)
            if canonical(after) != canonical(before):
                raise CollectionError("artifact source or evidence changed during evaluation")
            validate_result(result, before["metadata"], deadline)
            row = {"artifact_id": identity, "deadline_s": deadline, "evaluation_repeat": repeat,
                   "run_fingerprint": manifest["run_fingerprint"], "synthetic_data": manifest["synthetic_data"],
                   "source_sha256": before["source_sha256"], "result": result}
            row["record_sha256"] = value_hash(row)
            save_new(path, row)
            evaluated += 1
        verify_record(row, manifest, identity, deadline, repeat)
        if progress:
            progress({"completed_jobs": index, "total_jobs": len(jobs), "newly_evaluated": evaluated,
                      "artifact_id": identity, "deadline_s": deadline, "repeat": repeat})
    # Recheck every saved input, including an artifact executed early in the run.
    for slot in slots:
        if canonical(artifact_manifest(artifacts / slot["artifact_id"], slot, configs[slot["configuration_id"]], root)) != canonical(inputs[slot["artifact_id"]]):
            raise CollectionError("input changed before collection completed")
    return audit_collection(output)


def verify_record(row, manifest, identity, deadline, repeat):
    expected = (identity, deadline, repeat, manifest["run_fingerprint"], manifest["inputs"][identity]["source_sha256"])
    if (row.get("artifact_id"), row.get("deadline_s"), row.get("evaluation_repeat"), row.get("run_fingerprint"), row.get("source_sha256")) != expected:
        raise CollectionError("evaluation record identity/provenance mismatch")
    if row.get("record_sha256") != value_hash({k: v for k, v in row.items() if k != "record_sha256"}):
        raise CollectionError("saved evaluation record was modified")
    validate_result(row["result"], manifest["inputs"][identity]["metadata"], deadline)


def audit_collection(output):
    output = Path(output)
    manifest = json.loads((output / "collection_manifest.json").read_text())
    if manifest.get("run_fingerprint") != value_hash({k: v for k, v in manifest.items() if k != "run_fingerprint"}):
        raise CollectionError("collection manifest was modified")
    disagreements, records, probes = [], 0, 0
    selected_rows = []
    for identity, data in manifest["inputs"].items():
        for deadline in manifest["deadlines"]:
            repeated = []
            for repeat in range(1, 4):
                path = record_path(output, identity, deadline, repeat)
                if not path.is_file():
                    raise CollectionError("incomplete deadline/repeat matrix")
                row = json.loads(path.read_text())
                verify_record(row, manifest, identity, deadline, repeat)
                repeated.append(row)
                records += 1
                probes += len(row["result"].get("observations", []))
            disagree = len({behavior_signature(r["result"]) for r in repeated}) > 1
            if disagree:
                disagreements.append({"artifact_id": identity, "deadline_s": deadline,
                                      "repeat_passes": [r["result"]["primary_pass"] for r in repeated]})
            result = repeated[0]["result"]
            selected_rows.append({"artifact_id": identity, "deadline_s": deadline, "selected_repeat": 1,
                                  "primary_pass": result["primary_pass"], "clean_qualified": result["clean_qualified"],
                                  "source_sha256": data["source_sha256"], "reproducibility_disagreement": disagree})
    expected_records = len(manifest["inputs"]) * 9
    if len(list((output / "records").glob("*/*.json"))) != expected_records:
        raise CollectionError("unexpected or duplicated deadline/repeat records")
    summary = {"status": "SYNTHETIC SAVED-PROGRAM COLLECTION — NOT MODEL RESULTS" if manifest["synthetic_data"] else "saved-program collection",
        "synthetic_data": manifest["synthetic_data"], "cohort": manifest["cohort"],
        "programs": len(manifest["inputs"]), "evaluation_records": records, "executed_probes_all_repeats": probes,
        "expected_evaluation_records": expected_records, "complete_matrix": records == expected_records,
        "diagnostic_subset": manifest["diagnostic_subset"], "selected_repeat": 1,
        "reproducibility_disagreements": disagreements,
        "confirmatory_ready": manifest["cohort"] == "main" and not manifest["diagnostic_subset"] and
                              not manifest["synthetic_data"] and not disagreements,
        "run_fingerprint": manifest["run_fingerprint"], "selected_outcomes": selected_rows,
        "model_api_calls": 0}
    # Summary is derived; keep it out of the immutable source record set.
    (output / "collection_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cohort", choices=("main", "validation"), default="main")
    parser.add_argument("--artifact-id", action="append", help="diagnostic subset only; cannot supply main inference")
    args = parser.parse_args()
    last = [0.0]
    def progress(row):
        if time.monotonic() - last[0] > 20:
            print(json.dumps(row), flush=True)
            last[0] = time.monotonic()
    report = collect(args.artifacts, args.output, cohort=args.cohort, artifact_ids=args.artifact_id, progress=progress)
    print(json.dumps({k: v for k, v in report.items() if k != "selected_outcomes"}, indent=2))


if __name__ == "__main__":
    main()
