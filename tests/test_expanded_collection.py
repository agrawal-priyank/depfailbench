"""Prespecified repeats, immutable provenance and same-program deadline tables."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from benchmark.expanded.collect import CollectionError, audit_collection, collect, digest, record_path
from benchmark.expanded.collection_dry_run import write_control
from benchmark.expanded.contracts import scenarios
from benchmark.expanded.planning import allocation


def slot_for(index=0):
    return allocation()[1][index]


def prepare(tmp_path, slots=None):
    slots = slots or [slot_for()]
    for slot in slots:
        write_control(tmp_path / "artifacts" / slot["artifact_id"], slot, source="def create_app(transport, settings=None):\n    raise RuntimeError('synthetic')\n")
    return slots


def fake_evaluate(task, condition, *, source, settings, metadata):
    failure = metadata["generation_status"] != "completed"
    return {"task": task, "condition": condition, "deadline_s": settings.deadline_s,
        "metadata": metadata, "source_sha256": digest(source) if source.is_file() else None,
        "clean_qualified": not failure, "primary_pass": not failure,
        **({"generation_failure": metadata["generation_status"]} if failure else {}),
        "observations": [] if failure else [{"scenario": s, "pass": True, "outcome_class": "resilient_success", "responses": []} for s in scenarios(task)]}


def run_fake(tmp_path, slots=None, evaluator=fake_evaluate):
    slots = slots or [slot_for()]
    return collect(tmp_path / "artifacts", tmp_path / "collection", cohort="validation",
                   artifact_ids=[s["artifact_id"] for s in slots], evaluator=evaluator)


def test_same_saved_file_used_nine_times_and_resume_does_not_rerun(tmp_path):
    slots = prepare(tmp_path)
    calls = []
    def evaluate(*args, **kwargs):
        calls.append((kwargs["source"], digest(kwargs["source"]), kwargs["settings"].deadline_s))
        return fake_evaluate(*args, **kwargs)
    report = run_fake(tmp_path, evaluator=evaluate)
    assert report["programs"] == 1 and report["evaluation_records"] == 9 and report["diagnostic_subset"]
    assert [d for _, _, d in calls].count(1) == [d for _, _, d in calls].count(2) == [d for _, _, d in calls].count(5) == 3
    assert len({p for p, _, _ in calls}) == len({h for _, h, _ in calls}) == 1
    assert not report["confirmatory_ready"] and not report["reproducibility_disagreements"]
    def must_not_run(*args, **kwargs):
        raise AssertionError("completed evaluations must not rerun on restart")
    assert run_fake(tmp_path, evaluator=must_not_run)["evaluation_records"] == 9


def test_full_cohort_does_not_silently_shrink_to_available_artifacts(tmp_path):
    prepare(tmp_path)
    with pytest.raises(CollectionError, match="denominator"):
        collect(tmp_path / "artifacts", tmp_path / "collection", cohort="validation", evaluator=fake_evaluate)


@pytest.mark.parametrize("field,value", [("generation_status", "service_unfilled"), ("source_sha256", "wrong"), ("model_id", "wrong-model"), ("generation_settings", {})])
def test_inconsistent_artifact_metadata_rejected_before_execution(tmp_path, field, value):
    slot = prepare(tmp_path)[0]
    path = tmp_path / "artifacts" / slot["artifact_id"] / "metadata.json"
    metadata = json.loads(path.read_text()); metadata[field] = value; path.write_text(json.dumps(metadata))
    with pytest.raises(CollectionError):
        run_fake(tmp_path, evaluator=lambda *a, **k: pytest.fail("invalid inputs must not execute"))


@pytest.mark.parametrize("filename", ["prompt.txt", "configuration.json", "provenance.json"])
def test_missing_or_changed_evidence_rejected(tmp_path, filename):
    slot = prepare(tmp_path)[0]
    (tmp_path / "artifacts" / slot["artifact_id"] / filename).unlink()
    with pytest.raises(CollectionError, match="missing artifact evidence"):
        run_fake(tmp_path)


def test_saved_records_and_input_changes_cannot_be_silently_resumed(tmp_path):
    slot = prepare(tmp_path)[0]
    run_fake(tmp_path)
    path = record_path(tmp_path / "collection", slot["artifact_id"], 1, 1)
    row = json.loads(path.read_text()); row["result"]["primary_pass"] = False; path.write_text(json.dumps(row))
    with pytest.raises(CollectionError, match="modified"):
        audit_collection(tmp_path / "collection")
    source = tmp_path / "artifacts" / slot["artifact_id"] / "app.py"
    source.write_text("changed\n")
    with pytest.raises(CollectionError, match="source"):
        run_fake(tmp_path)


def test_source_mutation_during_execution_stops_collection(tmp_path):
    prepare(tmp_path)
    def mutate(*args, **kwargs):
        result = fake_evaluate(*args, **kwargs)
        kwargs["source"].write_text("changed\n")
        return result
    with pytest.raises(CollectionError, match="source|changed"):
        run_fake(tmp_path, evaluator=mutate)


def test_disagreement_is_reported_and_repeat_one_never_replaced_by_best(tmp_path):
    slot = prepare(tmp_path)[0]
    counts = {}
    def unstable(*args, **kwargs):
        row = fake_evaluate(*args, **kwargs)
        deadline = kwargs["settings"].deadline_s
        counts[deadline] = counts.get(deadline, 0) + 1
        if counts[deadline] == 2:
            row["primary_pass"] = False
            row["observations"][-1]["pass"] = False
        return row
    report = run_fake(tmp_path, evaluator=unstable)
    assert len(report["reproducibility_disagreements"]) == 3 and not report["confirmatory_ready"]
    for selected in report["selected_outcomes"]:
        first = json.loads(record_path(tmp_path / "collection", slot["artifact_id"], selected["deadline_s"], 1).read_text())
        assert selected["primary_pass"] == first["result"]["primary_pass"]
        assert selected["selected_repeat"] == 1


def test_returned_no_code_remains_in_all_deadline_denominators(tmp_path):
    slots = allocation()[1][:2]
    prepare(tmp_path, slots[:1])
    write_control(tmp_path / "artifacts" / slots[1]["artifact_id"], slots[1], status="no_code")
    report = run_fake(tmp_path, slots)
    assert report["programs"] == 2 and report["evaluation_records"] == 18
    assert sum(r["primary_pass"] for r in report["selected_outcomes"]) == 3


def test_export_retains_denominators_and_separates_raw_audit_repeats(tmp_path):
    pytest.importorskip("numpy")
    from benchmark.expanded.report_collection import export
    prepare(tmp_path)
    run_fake(tmp_path)
    report = export(tmp_path / "collection", tmp_path / "export", bootstraps=10)
    assert report["distinct_programs"] == 1 and report["deadline_rows_repeat_1"] == 3
    assert report["evaluation_records_including_audit_repeats"] == 9
    assert report["synthetic_data"] and "withheld" in report["primary_analysis_status"]
    assert not (tmp_path / "export/primary_analysis.json").exists()
    assert (tmp_path / "export/programs.csv").is_file()


def table_row(identity, deadline, passed, *, source_hash="constant"):
    return {"task": "E1", "condition": "C0", "deadline_s": deadline, "evaluation_repeat": 1,
            "metadata": {"artifact_id": identity, "cohort": "main", "task": "E1", "condition": "C0", "configuration_id": "gpt_6_1_sol", "model_id": "gpt-6.1-sol"},
            "primary_pass": passed, "clean_qualified": True, "source_sha256": source_hash,
            "observations": [{"scenario": s, "pass": passed, "responses": []} for s in scenarios("E1")]}


def test_deadline_table_records_both_improvement_and_worsening(tmp_path):
    pytest.importorskip("numpy")
    from benchmark.expanded.report_collection import tables
    rows = [table_row("a", d, d > 1) for d in (1, 2, 5)] + [table_row("b", d, d == 1) for d in (1, 2, 5)]
    report = tables(rows, bootstraps=10)
    assert all(r["same_saved_programs_n"] == 2 and r["improved"] == r["worsened"] == 1 for r in report["paired_deadlines"])
    assert all(r["generated_n"] == 2 for r in report["cells"])
    assert all(sum(r["disjoint_priority_counts"].values()) == r["failed_programs"] for r in report["failures"])
    bad = deepcopy(rows); bad[1]["source_sha256"] = "different"
    with pytest.raises(CollectionError, match="source"):
        tables(bad, bootstraps=10)
    with pytest.raises(CollectionError, match="missing"):
        tables(rows[:-1], bootstraps=10)
    bad = deepcopy(rows); bad[0]["evaluation_repeat"] = 2
    with pytest.raises(CollectionError, match="repeat 1"):
        tables(bad, bootstraps=10)


def test_failure_accounting_distinguishes_startup_and_checks_expected_recovery_at_each_deadline():
    from benchmark.expanded.failure_reporting import PRIORITY, failure_flags
    row = {"task": "E3", "deadline_s": 1, "primary_pass": False, "clean_qualified": True,
           "observations": [{"scenario": "cumulative_budget", "pass": False,
                             "outcome_class": "availability_failure", "responses": [{"status": 503}]}]}
    assert "safe_failure_where_recovery_required" not in failure_flags(row)
    row["deadline_s"] = 2
    assert "safe_failure_where_recovery_required" in failure_flags(row)
    row.update(clean_qualified=False, observations=[{"scenario": "clean", "pass": False,
               "startup_error": "SyntaxError", "outcome_class": "construction_failure", "responses": []}])
    flags = failure_flags(row)
    assert flags == {"startup_failure"}
    assert next(p for p in PRIORITY if p in flags) == "startup_failure"


def test_dependency_attempt_offsets_can_reconstruct_actual_request_timeline():
    from benchmark.expanded.evaluate import probe
    row = probe("E1", "transient_503")
    assert row["pass"]
    attempts = row["dependency"]["attempts"]
    assert len(attempts) == 3
    for i, attempt in enumerate(attempts):
        assert attempt["timing_origin"] == "public_request"
        assert 0 <= attempt["started_offset_s"] <= attempt["finished_offset_s"] <= row["responses"][0]["wall_latency_s"]
        assert attempt["finished_offset_s"]-attempt["started_offset_s"] == pytest.approx(attempt["elapsed_s"])
        if i:
            assert attempt["gap_since_previous_attempt_end_s"] == pytest.approx(attempt["started_offset_s"]-attempts[i-1]["finished_offset_s"])


async def test_startup_and_public_request_offsets_have_separate_origins():
    import httpx
    from time import monotonic
    from benchmark.expanded.contracts import Settings
    from benchmark.expanded.dependency import Dependency
    dependency = Dependency("E1", "clean", Settings())
    async with httpx.AsyncClient(transport=dependency, base_url="http://dependency.test", timeout=.25) as client:
        await client.get("/products/7")
        dependency.public_started = monotonic()
        await client.get("/products/7")
    assert dependency.attempts[0]["timing_origin"] == "dependency_initialization"
    assert dependency.attempts[1]["timing_origin"] == "public_request"
    assert dependency.attempts[1]["gap_since_previous_attempt_end_s"] is None
