import asyncio
import sys
from pathlib import Path

from benchmark.adapter_eval import evaluate
from benchmark.full_generate import prompt_from_manifest
from benchmark.task_registry import TaskRegistry


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "external_task"


def test_out_of_tree_adapter_loads_and_evaluates_without_core_registration(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    registry = TaskRegistry.from_manifest(EXAMPLE / "task_manifest.json")
    assert registry.ids() == ("EXAMPLE_RECORD",)
    result = asyncio.run(
        evaluate(EXAMPLE / "artifact", EXAMPLE / "task_manifest.json")
    )
    assert result["clean_qualified"] is True
    assert result["primary_pass"] is True
    assert result["timeout_guard"]["pass"] is True
    assert [row["outcome_class"] for row in result["observations"]] == [
        "resilient_success",
        "resilient_success",
        "safe_failure",
    ]


def test_registry_rejects_manifest_adapter_id_mismatch(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"schema_version":1,"task_api_version":1,"tasks":['
        '{"id":"WRONG","adapter":"example_task:TASK"}]}'
    )
    try:
        TaskRegistry.from_manifest(manifest)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("registry accepted a mismatched adapter ID")


def test_generation_prompt_assets_resolve_from_manifest(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    registry = TaskRegistry.from_manifest(EXAMPLE / "task_manifest.json")
    prompt = prompt_from_manifest(registry, "EXAMPLE_RECORD", "C1")
    assert "bounded retry and timeout" in prompt
    assert "@app.get(\"/lookup/{record_id}\")" in prompt
    assert "create_app(transport, settings)" in prompt
