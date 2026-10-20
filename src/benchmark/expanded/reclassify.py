"""Versioned classification of saved validation traces; no program execution.

Preserve the measured implementation/environment and link each derived record
to its immutable source record. Main-study post-hoc reclassification is excluded.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from .collect import (CollectionError, asset_manifest, audit_collection,
    implementation_manifest, record_path, save_new, validate_result, value_hash, verify_record)
from .contracts import Settings, TASKS, is_functional, public_requests, scenarios
from .oracles import ERROR_STATUS_POLICY_VERSION, classify, expected_status
from .planning import assets_root, digest


def policy_manifest():
    return {"version": ERROR_STATUS_POLICY_VERSION, "generic_dependency_errors": [502, 503, 504],
        "E6_unconfirmed_lost_acknowledgment_requires_503": True,
        "rows": [{"task": task, "scenario": scenario, "deadline_s": deadline,
                  "public_index": index,
                  "accepted_statuses": sorted(expected_status(task, scenario, Settings(deadline_s=deadline), index))}
                 for task in TASKS for scenario in scenarios(task) for deadline in (1, 2, 5)
                 for index, _ in enumerate(public_requests(task, scenario))]}


def derive_result(result, deadline):
    derived = deepcopy(result)
    for observation in derived.get("observations", []):
        observation.update(classify(derived["task"], observation["scenario"], Settings(deadline_s=deadline), observation))
    functional = [o for o in derived.get("observations", []) if is_functional(o["scenario"])]
    needed = {s for s in scenarios(derived["task"]) if is_functional(s)}
    qualified = (not derived.get("generation_failure") and {o["scenario"] for o in functional} == needed
                 and all(o["pass"] for o in functional))
    if qualified != result["clean_qualified"]:
        raise CollectionError("functional qualification changed; saved fault coverage needs separate review")
    derived["clean_qualified"] = qualified
    derived["primary_pass"] = bool(qualified and not derived.get("generation_failure")
        and {o["scenario"] for o in derived["observations"]} == set(scenarios(derived["task"]))
        and all(o["pass"] for o in derived["observations"]))
    return derived


def reclassify_collection(source, destination, *, reason, root=None):
    source, destination, root = Path(source), Path(destination), assets_root(root)
    if not reason.strip():
        raise CollectionError("document the author-approved reason for classification")
    if destination.exists():
        raise CollectionError("refusing to overwrite a classification directory")
    if destination.resolve().is_relative_to(source.resolve()):
        raise CollectionError("classification output must be outside original evidence")
    original = json.loads((source / "collection_manifest.json").read_text())
    if original["cohort"] != "validation" or original.get("reclassification"):
        raise CollectionError("only original validation traces may be classified by this command")
    if original["run_fingerprint"] != value_hash({k: v for k, v in original.items() if k != "run_fingerprint"}):
        raise CollectionError("source manifest was modified")
    if original["assets"] != asset_manifest(root) or original["settings"] != asdict(Settings()):
        raise CollectionError("task assets/settings differ; raw traces cannot establish a changed experiment")
    current = implementation_manifest()
    if (set(current) - set(original["implementation"])) - {"reclassify.py"}:
        raise CollectionError("unexpected implementation addition")
    if any(current.get(k) != v for k, v in original["implementation"].items() if k != "oracles.py"):
        raise CollectionError("a non-oracle measurement component changed")
    if original["deadlines"] != [1, 2, 5] or original["repeats"] != 3:
        raise CollectionError("complete fixed deadline/repeat matrix required")
    jobs = [(identity, deadline, repeat, record_path(source, identity, deadline, repeat))
            for identity in original["inputs"] for deadline in original["deadlines"] for repeat in (1, 2, 3)]
    paths = [path for _, _, _, path in jobs]
    if set((source / "records").glob("*/*.json")) != set(paths):
        raise CollectionError("incomplete or unexpected source records")
    source_hashes = {str(p.relative_to(source)): digest(p) for p in [source / "collection_manifest.json", *paths]}
    prepared = []
    changed_probes = changed_records = 0
    for identity, deadline, repeat, path in jobs:
        row = json.loads(path.read_text())
        verify_record(row, original, identity, deadline, repeat)
        derived = derive_result(row["result"], deadline)
        validate_result(derived, original["inputs"][identity]["metadata"], deadline)
        changed_probes += sum(any(a[k] != b[k] for k in ("pass", "outcome_class", "notes"))
                              for a, b in zip(row["result"]["observations"], derived["observations"]))
        changed_records += derived["primary_pass"] != row["result"]["primary_pass"]
        prepared.append((row, derived))
    invariant = {k: deepcopy(v) for k, v in original.items() if k != "run_fingerprint"}
    invariant["reclassification"] = {"reason": reason,
        "source_run_fingerprint": original["run_fingerprint"], "source_files_sha256": source_hashes,
        "classification_implementation": current, "policy": policy_manifest(),
        "measured_implementation_retained_in_manifest": True,
        "model_api_calls": 0, "program_executions": 0}
    manifest = {**invariant, "run_fingerprint": value_hash(invariant)}
    destination.mkdir(parents=True, exist_ok=False)
    save_new(destination / "collection_manifest.json", manifest)
    for old, result in prepared:
        row = {k: deepcopy(v) for k, v in old.items() if k != "record_sha256"}
        row.update(result=result, run_fingerprint=manifest["run_fingerprint"],
                   source_measurement_record_sha256=old["record_sha256"])
        row["record_sha256"] = value_hash(row)
        verify_record(row, manifest, row["artifact_id"], row["deadline_s"], row["evaluation_repeat"])
        save_new(record_path(destination, row["artifact_id"], row["deadline_s"], row["evaluation_repeat"]), row)
    if source_hashes != {relative: digest(source / relative) for relative in source_hashes}:
        raise CollectionError("original evidence changed during classification")
    summary = audit_collection(destination)
    report = {"policy_version": ERROR_STATUS_POLICY_VERSION, "programs": summary["programs"],
        "records": summary["evaluation_records"], "changed_probe_classifications": changed_probes,
        "changed_all_check_record_outcomes": changed_records,
        "reproducibility_disagreements": summary["reproducibility_disagreements"],
        "source_files_verified_unchanged": True, "measured_environment_retained": True,
        "cohort": "validation", "model_api_calls": 0, "program_executions": 0}
    save_new(destination / "reclassification_summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    print(json.dumps(reclassify_collection(args.source, args.output, reason=args.reason), indent=2))


if __name__ == "__main__":
    main()
