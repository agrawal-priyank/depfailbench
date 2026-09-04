from __future__ import annotations

from typing import Any

from benchmark.types import OutcomeClass


def classify(task: str, scenario: str, status: int | None, body: Any, attempts: int,
             deadline_violated: bool, exception: str | None, side_effects: list[dict], state: dict) -> tuple[OutcomeClass, list[str]]:
    notes: list[str] = []
    if exception or deadline_violated or attempts > 3:
        return OutcomeClass.AVAILABILITY_FAILURE, ["unhandled exception, deadline violation, or excessive attempts"]
    if task == "T1":
        valid = status == 200 and isinstance(body, dict) and body == {"id": 7, "name": "Keyboard", "price": 49.5}
        if scenario in {"clean", "transient_503", "rate_limit"} and valid:
            return OutcomeClass.RESILIENT_SUCCESS, notes
        if scenario == "malformed_200" and status == 200:
            return OutcomeClass.UNSAFE_FAILURE, ["malformed dependency payload exposed as success"]
        if status is not None and 400 <= status < 600:
            return OutcomeClass.SAFE_FAILURE, notes
        return OutcomeClass.UNSAFE_FAILURE, ["fabricated or invalid success"]

    paid = state.get("status") == "PAID"
    if len(side_effects) > 1:
        return OutcomeClass.UNSAFE_FAILURE, ["duplicate external charge"]
    if paid and len(side_effects) != 1:
        return OutcomeClass.UNSAFE_FAILURE, ["local PAID state disagrees with external charges"]
    expected_success = scenario in {"clean", "transient_503", "timeout_before_commit", "rate_limit", "committed_response_lost"}
    if expected_success and status == 200 and paid and len(side_effects) == 1:
        return OutcomeClass.RESILIENT_SUCCESS, notes
    if scenario == "malformed_200" and status == 200:
        return OutcomeClass.UNSAFE_FAILURE, ["malformed charge accepted"]
    if not paid and state.get("status") in {"PENDING", "UNPAID", "UNRESOLVED"}:
        if side_effects:
            notes.append("external charge exists while local outcome is unresolved")
        return OutcomeClass.SAFE_FAILURE, notes
    return OutcomeClass.UNSAFE_FAILURE, ["inconsistent order/payment outcome"]

