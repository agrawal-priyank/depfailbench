"""Contract-based status choices must never mask recovery or safety failures."""

from copy import deepcopy

import pytest

from benchmark.expanded.contracts import Settings
from benchmark.expanded.oracles import classify, expected_status


def evidence(status, *, latency=.01):
    return {"responses": [{"status": status, "body": {}, "wall_latency_s": latency}],
        "dependency": {"attempts": [{"query": {}, "status": 503}], "effects": [],
                       "contract_violations": [], "stock": {"widget": 10, "gadget": 8}},
        "application_state": {}}


@pytest.mark.parametrize("task,scenario", [
    ("E1", "persistent_503"), ("E1", "hanging_dependency"),
    ("E1", "retry_after_exceeds_deadline"), ("E1", "malformed_200"),
    ("E1", "wrong_identity"), ("E2", "persistent_503"),
    ("E3", "malformed_200"), ("E4", "cursor_cycle"),
    ("E5", "persistent_503"), ("E6", "malformed_200"), ("E7", "malformed_200"),
])
@pytest.mark.parametrize("status", [502, 503, 504])
def test_unspecified_dependency_error_code_is_not_an_extra_requirement(task, scenario, status):
    assert classify(task, scenario, Settings(), evidence(status))["pass"]


@pytest.mark.parametrize("task,scenario,code", [
    ("E1", "not_found", 404), ("E2", "no_valid_quotes", 404),
    ("E2", "invalid_input", 422), ("E6", "invalid_input", 422),
    ("E8", "invalid_input", 422), ("E6", "insufficient_stock", 409),
    ("E2", "malformed_200", 502), ("E2", "conflicting_quote", 502),
    ("E3", "cursor_cycle", 502), ("E3", "conflicting_duplicate", 502),
    ("E4", "conflicting_duplicate", 502),
    ("E8", "malformed_200", 502), ("E8", "persistent_503", 503),
    ("E8", "hanging_dependency", 503), ("E8", "retry_after_exceeds_deadline", 503),
])
def test_explicit_task_statuses_remain_exact(task, scenario, code):
    assert expected_status(task, scenario, Settings(), 0) == {code}
    if code in {502, 503}:
        for other in {502, 503, 504} - {code}:
            assert not classify(task, scenario, Settings(), evidence(other))["pass"]


def test_conflicting_identity_keeps_first_success_and_second_conflict():
    assert expected_status("E6", "conflicting_identity", Settings(), 0) == {200}
    assert expected_status("E6", "conflicting_identity", Settings(), 1) == {409}


@pytest.mark.parametrize("scenario", ["transient_503", "timeout_before_commit", "rate_limit", "committed_response_lost"])
@pytest.mark.parametrize("status", [502, 503, 504])
def test_feasible_recovery_still_requires_success(scenario, status):
    assert expected_status("E5", scenario, Settings(), 0) == {200}
    assert not classify("E5", scenario, Settings(), evidence(status))["pass"]


def test_cumulative_budget_keeps_the_deadline_dependent_recovery_requirement():
    assert expected_status("E3", "cumulative_budget", Settings(deadline_s=1), 0) == {502, 503, 504}
    assert expected_status("E3", "cumulative_budget", Settings(deadline_s=2), 0) == {200}
    assert expected_status("E3", "cumulative_budget", Settings(deadline_s=5), 0) == {200}


@pytest.mark.parametrize("status", [200, 404, 429, 500])
def test_generic_error_acceptance_is_not_any_status_or_false_success(status):
    assert not classify("E1", "persistent_503", Settings(), evidence(status))["pass"]


@pytest.mark.parametrize("defect", ["deadline", "watchdog", "attempt_budget", "missing_dependency"])
def test_allowed_error_cannot_hide_timing_or_attempt_violations(defect):
    row = evidence(504)
    if defect == "deadline":
        row["responses"][0]["wall_latency_s"] = 1.051
    elif defect == "watchdog":
        row["watchdog_intervened"] = True
    elif defect == "attempt_budget":
        row["dependency"]["contract_violations"] = ["logical-operation attempt budget exceeded"]
    else:
        row["dependency"]["attempts"] = []
    assert not classify("E1", "hanging_dependency", Settings(), row)["pass"]


def test_unconfirmed_lost_acknowledgment_preserves_explicit_503_and_state():
    row = evidence(503)
    row["dependency"]["effects"] = [{"request_id": "request-1", "reservation_id": "r1", "item_id": "widget", "quantity": 3, "status": "reserved"}]
    row["dependency"]["stock"]["widget"] = 7
    row["application_state"] = {"reservations": {"request-1": "UNRESOLVED"}}
    assert classify("E6", "malformed_200", Settings(), row)["pass"]
    for status in (502, 504):
        row["responses"][0]["status"] = status
        lost = classify("E6", "committed_response_lost", Settings(), row)
        assert not lost["pass"]
        assert "unconfirmed committed reservation requires HTTP 503" in lost["notes"]
    row["responses"][0]["status"] = 503
    lost = classify("E6", "committed_response_lost", Settings(), row)
    assert not lost["pass"]  # This fixture permits recovery, which still needs 200.
    assert "unconfirmed committed reservation requires HTTP 503" not in lost["notes"]
    row["responses"][0]["status"] = 503
    row["application_state"]["reservations"]["request-1"] = "REJECTED"
    assert not classify("E6", "malformed_200", Settings(), row)["pass"]


def test_allowed_error_cannot_hide_duplicate_effects_or_false_paid_state():
    row = evidence(502)
    row["dependency"]["effects"] = [{"order_id": "order-1", "charge_id": "c1"}]
    row["application_state"] = {"orders": {"order-1": "UNRESOLVED"}}
    assert classify("E5", "malformed_200", Settings(), row)["pass"]
    bad = deepcopy(row)
    bad["dependency"]["effects"].append({"order_id": "order-1", "charge_id": "c2"})
    assert not classify("E5", "malformed_200", Settings(), bad)["pass"]
    row["application_state"]["orders"]["order-1"] = "PAID"
    assert not classify("E5", "malformed_200", Settings(), row)["pass"]
