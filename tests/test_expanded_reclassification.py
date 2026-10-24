"""Saved-trace rescoring is linked, complete, immutable and execution-free."""

from copy import deepcopy
import json

import pytest

from benchmark.expanded.collect import CollectionError, collect, digest, record_path, value_hash
from benchmark.expanded.collection_dry_run import write_control
from benchmark.expanded.contracts import scenarios
from benchmark.expanded.oracles import classify
from benchmark.expanded.planning import allocation
from benchmark.expanded.reclassify import reclassify_collection


def prepare_source(tmp_path):
    slot = next(s for s in allocation()[1] if s["task"] == "E1" and s["condition"] == "C0")
    write_control(tmp_path / "artifacts" / slot["artifact_id"], slot, source="not executed")
    def saved_evidence(task, condition, *, source, settings, metadata):
        observations = []
        for scenario in scenarios(task):
            status = 404 if scenario == "not_found" else 502 if scenario in {
                "persistent_503", "malformed_200", "wrong_identity"} else 503 if scenario in {
                "hanging_dependency", "retry_after_exceeds_deadline"} else 200
            body = {"id": 19, "name": "Mouse", "price": 12.0} if scenario == "alternate_clean" else {
                "id": 7, "name": "Keyboard", "price": 49.5}
            observation = {"scenario": scenario, "responses": [{"status": status, "body": body, "wall_latency_s": .01}],
                "dependency": {"attempts": [{}], "effects": [], "contract_violations": []}, "application_state": {}}
            observation.update(classify(task, scenario, settings, observation))
            if scenario == "persistent_503":
                observation.update({"pass": False, "outcome_class": "availability_failure",
                                    "notes": ["unexpected status 502 on public request 0"]})
            observations.append(observation)
        return {"task": task, "condition": condition, "deadline_s": settings.deadline_s,
            "metadata": metadata, "source_sha256": digest(source), "clean_qualified": True,
            "primary_pass": False, "observations": observations}
    source = tmp_path / "source"
    collect(tmp_path / "artifacts", source, cohort="validation", artifact_ids=[slot["artifact_id"]], evaluator=saved_evidence)
    return source, slot


def test_original_records_and_measurement_environment_survive_reclassification(tmp_path, monkeypatch):
    source, slot = prepare_source(tmp_path)
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError("classification must not execute a program")
    monkeypatch.setattr("benchmark.expanded.evaluate.probe", forbidden)
    monkeypatch.setattr("benchmark.expanded.collect.evaluate", forbidden)
    destination = tmp_path / "derived"
    result = reclassify_collection(source, destination, reason="author-approved contract correction")
    assert result["records"] == 9 and result["changed_all_check_record_outcomes"] == 9
    assert result["changed_probe_classifications"] == 9
    assert result["model_api_calls"] == result["program_executions"] == 0
    assert result["reproducibility_disagreements"] == []
    assert before == {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    old_manifest = json.loads((source / "collection_manifest.json").read_text())
    new_manifest = json.loads((destination / "collection_manifest.json").read_text())
    assert old_manifest["environment"] == new_manifest["environment"]
    assert old_manifest["implementation"] == new_manifest["implementation"]
    for deadline in (1, 2, 5):
        for repeat in (1, 2, 3):
            old = json.loads(record_path(source, slot["artifact_id"], deadline, repeat).read_text())
            new = json.loads(record_path(destination, slot["artifact_id"], deadline, repeat).read_text())
            assert not old["result"]["primary_pass"] and new["result"]["primary_pass"]
            assert new["source_measurement_record_sha256"] == old["record_sha256"]
            assert new["source_sha256"] == old["source_sha256"]
            for a, b in zip(old["result"]["observations"], new["result"]["observations"]):
                assert {k:v for k,v in a.items() if k not in {"pass", "notes", "outcome_class"}} == {
                    k:v for k,v in b.items() if k not in {"pass", "notes", "outcome_class"}}
    with pytest.raises(CollectionError, match="overwrite"):
        reclassify_collection(source, destination, reason="do not overwrite")


@pytest.mark.parametrize("defect", ["missing", "tampered", "coordinate", "main", "worker"])
def test_unsafe_or_incomplete_source_cannot_create_derived_results(tmp_path, defect):
    source, slot = prepare_source(tmp_path)
    path = record_path(source, slot["artifact_id"], 1, 1)
    if defect == "missing":
        path.unlink()
    elif defect in {"tampered", "coordinate"}:
        row = json.loads(path.read_text())
        row["evaluation_repeat"] = 2
        if defect == "coordinate":
            row["record_sha256"] = value_hash({k:v for k,v in row.items() if k != "record_sha256"})
        path.write_text(json.dumps(row))
    else:
        path = source / "collection_manifest.json"
        manifest = json.loads(path.read_text())
        if defect == "main":
            manifest["cohort"] = "main"
        else:
            manifest["implementation"]["worker.py"] = "changed"
        manifest["run_fingerprint"] = value_hash({k:v for k,v in manifest.items() if k != "run_fingerprint"})
        path.write_text(json.dumps(manifest))
    with pytest.raises(CollectionError):
        reclassify_collection(source, tmp_path / "derived", reason="test guard")
    assert not (tmp_path / "derived").exists()


def test_derived_outputs_cannot_be_written_inside_original_evidence(tmp_path):
    source, _ = prepare_source(tmp_path)
    with pytest.raises(CollectionError, match="outside"):
        reclassify_collection(source, source / "new", reason="test immutability")
