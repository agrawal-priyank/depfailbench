"""Scientific controls: fair treatment, real elapsed time and seeded defects."""

import shutil
import time

import pytest

from benchmark.expanded.contracts import Settings, TASKS, scenarios
from benchmark.expanded.evaluate import evaluate, probe
from benchmark.expanded.oracles import matches
from benchmark.expanded.planning import allocation, assets_root, check


def test_expanded_allocation_reuses_baselines_and_excludes_validation():
    report = check()
    assert (report["main_slots"], report["primary_slots"], report["extra_setting_slots"]) == (4800, 3360, 1440)
    assert report["excluded_validation_slots"] == 160
    main, validation = allocation()
    assert (main, validation) == allocation()
    assert {r["cohort"] for r in validation} == {"validation"}
    assert set(r["artifact_id"] for r in main).isdisjoint(r["artifact_id"] for r in validation)


def test_common_prompt_change_in_one_condition_is_rejected(tmp_path):
    root = tmp_path / "assets"
    shutil.copytree(assets_root(), root)
    p = root / "prompts/E5_C1.md"
    p.write_text(p.read_text().replace("default 1.0 second", "default 2.0 seconds"))
    with pytest.raises(ValueError, match="undeclared change"):
        check(root)


@pytest.mark.parametrize("actual,expected", [(7.0, 7), (True, 1), (0, False), ({"quantity": True}, {"quantity": 1})])
def test_typed_oracles_do_not_accept_python_equality_shortcuts(actual, expected):
    assert not matches(actual, expected)


@pytest.mark.parametrize("task", list(TASKS))
def test_both_conditions_receive_every_applicable_check(monkeypatch, task):
    def fake_probe(task_id, scenario, **kwargs):
        return {"scenario": scenario, "pass": True, "outcome_class": "resilient_success"}
    monkeypatch.setattr("benchmark.expanded.evaluate.probe", fake_probe)
    c0, c1 = evaluate(task, "C0"), evaluate(task, "C1")
    assert c0["primary_pass"] and c1["primary_pass"]
    assert c0["observations"] == c1["observations"]
    assert {r["scenario"] for r in c0["observations"]} == set(scenarios(task))
    assert "hanging_dependency" in {r["scenario"] for r in c0["observations"]}


@pytest.mark.parametrize("task,scenario,mutation,reason", [
    ("E1", "transient_503", "no_retry", "unexpected status"),
    ("E1", "malformed_200", "false_success", "unexpected status"),
    ("E3", "clean", "partial_pages", "incomplete"),
    ("E4", "identical_overlap", "double_count", "incomplete"),
    ("E5", "committed_response_lost", "duplicate_action", "duplicate non-idempotent"),
    ("E7", "clean", "wrong_key", "downstream method/path"),
    ("E8", "preference_replacement", "preference_patch", "downstream method/path"),
])
def test_seeded_defects_are_detected(task, scenario, mutation, reason):
    row = probe(task, scenario, mutation=mutation)
    assert not row["pass"], row
    assert any(reason in n for n in row["notes"]), row


def test_timeout_fixture_consumes_actual_elapsed_time():
    settings = Settings(timeout_s=.03, deadline_s=.2)
    row = probe("E1", "hanging_dependency", settings=settings)
    assert row["pass"], row
    assert row["responses"][0]["wall_latency_s"] >= .08
    assert sum(a["elapsed_s"] for a in row["dependency"]["attempts"]) >= .08
    assert row["timing_basis"] == "actual_monotonic_wall_clock"


def test_blocking_program_is_terminated_by_parent_not_event_loop(tmp_path):
    source = tmp_path / "app.py"
    source.write_text('''import time
from fastapi import FastAPI
def create_app(transport, settings=None):
    app = FastAPI()
    @app.get('/products/{product_id}')
    async def endpoint(product_id: int):
        time.sleep(10)
        return {'id': product_id, 'name':'Keyboard', 'price':49.5}
    return app
''')
    start = time.monotonic()
    row = probe("E1", "clean", source=source, settings=Settings(timeout_s=.03, deadline_s=.05))
    assert row["watchdog_intervened"] and not row["pass"], row
    assert time.monotonic() - start < 3


def test_startup_failure_is_retained_in_unconditional_result(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("raise RuntimeError('deliberate startup defect')\n")
    result = evaluate("E1", "C0", source=source)
    assert not result["clean_qualified"] and not result["primary_pass"]
    assert "deliberate startup defect" in result["observations"][0]["startup_error"]
    assert result["source_sha256"]


@pytest.mark.parametrize("status", ["truncated", "refused", "incomplete", "no_code"])
def test_unsuccessful_returned_generations_are_not_replaced(status, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("incomplete generation must not launch execution or replacement")
    monkeypatch.setattr("benchmark.expanded.evaluate.probe", forbidden)
    result = evaluate("E1", "C1", metadata={"generation_status": status})
    assert result["generation_failure"] == status
    assert result["primary_pass"] is False


def test_no_visible_code_needs_no_source_file(tmp_path):
    result = evaluate("E1", "C0", source=tmp_path / "absent.py", metadata={"generation_status": "no_code"})
    assert result["generation_failure"] == "no_code"
    assert not result["primary_pass"]


@pytest.mark.asyncio
async def test_invalid_preference_types_are_rejected_before_dependency_work():
    import httpx
    from benchmark.expanded.reference import create_reference
    from benchmark.expanded.dependency import Dependency
    settings = Settings()
    dependency = Dependency("E8", "clean", settings)
    app = create_reference("E8", dependency, settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://artifact.test") as client:
        response = await client.put("/preferences/alice", json={"language": []})
    assert response.status_code == 422
    assert dependency.attempts == []
