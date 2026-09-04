import json

import pytest

from benchmark.runner import run_matrix, run_probe
from benchmark.metrics import summarize


@pytest.mark.parametrize("task,scenario", [
    ("T1", "clean"), ("T1", "transient_503"), ("T1", "persistent_503"),
    ("T1", "timeout"), ("T1", "rate_limit"), ("T1", "malformed_200"),
    ("T4", "clean"), ("T4", "transient_503"), ("T4", "persistent_503"),
    ("T4", "timeout_before_commit"), ("T4", "rate_limit"),
    ("T4", "malformed_200"), ("T4", "committed_response_lost"),
])
async def test_resilient_reference_oracle(task, scenario):
    result = await run_probe(task, "reference_resilient", scenario)
    expected = "safe_failure" if scenario in {"persistent_503", "timeout", "malformed_200"} else "resilient_success"
    assert result.outcome_class == expected
    assert not result.deadline_violated
    assert len(result.attempts) <= 3
    assert result.duplicate_side_effects == 0


@pytest.mark.parametrize("task", ["T1", "T4"])
async def test_naive_reference_passes_clean(task):
    result = await run_probe(task, "reference_naive", "clean")
    assert result.outcome_class == "resilient_success"


async def test_naive_reference_exposes_expected_weaknesses():
    t1_transient = await run_probe("T1", "reference_naive", "transient_503")
    t1_malformed = await run_probe("T1", "reference_naive", "malformed_200")
    t4_ambiguous = await run_probe("T4", "reference_naive", "committed_response_lost")
    assert t1_transient.outcome_class == "safe_failure"
    assert t1_malformed.outcome_class == "unsafe_failure"
    assert t4_ambiguous.outcome_class == "safe_failure"
    assert len(t4_ambiguous.side_effects) == 1
    assert t4_ambiguous.final_state["status"] == "UNRESOLVED"


async def test_repeated_runs_are_deterministic_except_wall_latency():
    rows = await run_matrix(repetitions=3)
    signatures = {}
    for row in rows:
        data = row.to_dict()
        data.pop("latency_s")
        key = (row.task, row.fixture, row.scenario)
        signatures.setdefault(key, set()).add(json.dumps(data, sort_keys=True))
    assert all(len(values) == 1 for values in signatures.values())


async def test_aggregate_metrics_separate_controls():
    summary = summarize(await run_matrix(repetitions=1))
    assert summary["reference_naive"]["CCR"] == 1.0
    assert summary["reference_naive"]["APR"] == 0.0
    assert summary["reference_resilient"]["CCR"] == 1.0
    assert summary["reference_resilient"]["APR"] == 1.0
