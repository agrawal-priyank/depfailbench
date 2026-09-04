import json

from benchmark.pilot import execute


def _write_artifact(root, slot, kind):
    directory = root / slot["artifact_id"]
    directory.mkdir(parents=True)
    metadata = {
        "artifact_id": slot["artifact_id"],
        "task": slot["task"],
        "condition": slot["condition"],
        "model_provider": "test",
        "model_family": slot["model"],
        "model_version": "test-v1",
        "generation_index": slot["generation_index"],
    }
    (directory / "metadata.json").write_text(json.dumps(metadata))
    module = "t1" if slot["task"] == "T1" else "t4"
    (directory / "app.py").write_text(
        f"from benchmark.fixtures.{module} import create_app as reference\n"
        "def create_app(transport, settings=None):\n"
        f"    return reference('{kind}', transport, settings)\n"
    )


async def test_complete_balanced_pilot_writes_machine_and_human_reports(tmp_path):
    plan = json.loads(open("generation_plan.json").read())
    artifacts = tmp_path / "artifacts"
    for slot in plan["slots"]:
        kind = "reference_naive" if slot["condition"] == "C0" else "reference_resilient"
        _write_artifact(artifacts, slot, kind)

    output = tmp_path / "results"
    # Write the unchanged plan into the isolated test directory.
    plan_path = tmp_path / "generation_plan.json"
    plan_path.write_text(json.dumps(plan))
    summary = await execute(plan_path, artifacts, output)

    assert summary["pilot_complete"] is True
    assert summary["status_counts"] == {"evaluated": 16}
    assert summary["cells"]["openai_gpt56sol:C0"]["APR"] == 0.0
    assert summary["cells"]["openai_gpt56sol:C1"]["APR"] == 1.0
    assert len((output / "artifact_manifest.jsonl").read_text().splitlines()) == 16
    assert "**Status:** complete" in (output / "pilot_report.md").read_text()


async def test_missing_artifacts_are_explicit_and_not_scored_as_zero(tmp_path):
    plan = json.loads(open("generation_plan.json").read())
    plan_path = tmp_path / "generation_plan.json"
    plan_path.write_text(json.dumps(plan))
    summary = await execute(plan_path, tmp_path / "artifacts", tmp_path / "results")
    assert summary["pilot_complete"] is False
    assert summary["status_counts"] == {"missing": 16}
    assert summary["overall"]["CCR"] is None
