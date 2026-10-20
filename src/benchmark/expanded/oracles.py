"""Independent checks of responses, traces and externally observed effects."""

from __future__ import annotations

from collections import Counter
import hashlib

from .contracts import TASKS, SAFE_UNAVAILABLE, catalog_items, events, public_requests


def matches(actual, expected):
    """Typed subset matching; bool and float are not integer IDs or quantities."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and matches(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(matches(a, b) for a, b in zip(actual, expected))
    if type(expected) is float:
        return type(actual) in {int, float} and actual == expected
    return type(actual) is type(expected) and actual == expected


def expected_status(task_id, scenario, settings, public_index):
    if scenario == "invalid_input":
        return {422}
    if scenario in {"not_found", "no_valid_quotes"}:
        return {404}
    if scenario == "insufficient_stock" or (scenario == "conflicting_identity" and public_index == 1):
        return {409}
    if scenario in SAFE_UNAVAILABLE:
        return {503}
    if scenario in {"malformed_200", "wrong_identity", "cursor_cycle", "conflicting_duplicate", "conflicting_quote"}:
        return {502, 503} if TASKS[task_id].pattern == "action" else {502}
    if scenario == "cumulative_budget" and settings.deadline_s < 6 * settings.timeout_s * .8 + .03:
        return {503}
    return {200}


def expected_body(task_id, scenario, public, snapshot):
    if task_id == "E1":
        product = int(public["path"].split("/")[-1])
        return {"id": product, "name": "Keyboard" if product == 7 else "Mouse",
                "price": 49.5 if product == 7 else 12.0}
    if task_id == "E2":
        quote = ("a", 500, 2) if scenario == "quote_tie" else (
            ("other", 450, 4) if scenario == "alternate_clean" else ("cheap", 500, 3))
        return {"quote_id": quote[0], "price_cents": quote[1], "currency": "USD", "delivery_days": quote[2]}
    if task_id in {"E3", "E4"}:
        rows = catalog_items(scenario) if task_id == "E3" else events(scenario)
        if scenario == "identical_overlap":
            rows = rows[:2] + rows[3:]
        if task_id == "E3":
            return {"items": rows}
        counts = Counter(row["user_id"] for row in rows if row["event_type"] == "login" and row["outcome"] == "failure")
        return {"failed_logins": [{"user_id": u, "count": counts[u]} for u in sorted(counts)]}
    if task_id == "E5":
        order = public["path"].split("/")[2]
        charges = [x for x in snapshot["effects"] if x.get("order_id") == order]
        return {"order_id": order, "status": "PAID", "charge_id": charges[0]["charge_id"]} if len(charges) == 1 else None
    if task_id == "E6":
        identity = public["path"].split("/")[-1]
        rows = [x for x in snapshot["effects"] if x.get("request_id") == identity]
        return {k: rows[0][k] for k in ("reservation_id", "request_id", "item_id", "quantity", "status")} if len(rows) == 1 else None
    if task_id == "E7":
        return {"key": public["path"].split("/")[-1], "sha256": hashlib.sha256(public["json"]["content"].encode()).hexdigest()}
    return {"user_id": public["path"].split("/")[-1],
            "preferences": {"language": "en", "email_notifications": True, **public["json"]}}


def classify(task_id, scenario, settings, evidence):
    notes = []
    snapshot = evidence.get("dependency") or {"attempts": [], "effects": [], "contract_violations": []}
    responses = evidence.get("responses", [])
    if evidence.get("startup_error"):
        return {"pass": False, "outcome_class": "construction_failure", "notes": [evidence["startup_error"]]}
    if evidence.get("watchdog_intervened") or evidence.get("request_error"):
        return {"pass": False, "outcome_class": "availability_failure", "notes": ["request failed or independent watchdog intervened"]}
    if snapshot.get("contract_violations"):
        notes += snapshot["contract_violations"]
    requests = public_requests(task_id, scenario)
    if len(responses) != len(requests):
        notes.append("public response count differs from scenario contract")
    for i, (public, response) in enumerate(zip(requests, responses)):
        if response.get("wall_latency_s", float("inf")) > settings.deadline_s + .05:
            notes.append("actual whole-request deadline exceeded")
        status = response.get("status")
        if status not in expected_status(task_id, scenario, settings, i):
            notes.append(f"unexpected status {status} on public request {i}")
        if status == 200:
            expected = expected_body(task_id, scenario, public, snapshot)
            if expected is None or not matches(response.get("body"), expected):
                notes.append("success body is incomplete, incorrectly typed or unconfirmed")
    if scenario == "invalid_input":
        if snapshot["attempts"]:
            notes.append("invalid public input reached the dependency")
    elif not snapshot["attempts"]:
        notes.append("required dependency operation was never performed")
    task = TASKS[task_id]
    state = evidence.get("application_state", {})
    if task.pattern == "pages" and responses and responses[-1].get("status") == 200:
        expected_pages = 1 if scenario == "empty_history" else 3
        seen = {x["query"].get("cursor") for x in snapshot["attempts"] if x.get("status") == 200}
        if len(seen) != expected_pages:
            notes.append("success was returned without the complete required page traversal")
    if task.pattern == "action":
        effects = snapshot["effects"]
        if len(effects) > 1:
            notes.append("duplicate non-idempotent effect")
        first = requests[0]
        identity = first["path"].split("/")[2] if task_id == "E5" else first["path"].split("/")[-1]
        table = state.get("orders" if task_id == "E5" else "reservations", {})
        record = table.get(identity) if isinstance(table, dict) else None
        # The task specifies a keyed status, not its internal representation.
        # The public receipt is checked against the external effect above.
        label_state = record.get("status") if isinstance(record, dict) else record
        if effects and responses and responses[0].get("status") == 200:
            label = "PAID" if task_id == "E5" else "RESERVED"
            receipt_key = "charge_id" if task_id == "E5" else "reservation_id"
            wrong_stored_receipt = (isinstance(record, dict) and receipt_key in record
                                    and record[receipt_key] != effects[0].get(receipt_key))
            if label_state != label or wrong_stored_receipt:
                notes.append("application state does not match confirmed external receipt")
        elif effects and label_state != "UNRESOLVED":
            notes.append("committed but unconfirmed action must be UNRESOLVED")
        elif not effects and label_state in ("PAID", "RESERVED"):
            notes.append("application claims success without external effect")
        if task_id == "E6":
            expected_stock = {"widget": 10, "gadget": 8}
            for effect in effects:
                expected_stock[effect["item_id"]] -= effect["quantity"]
            if snapshot["stock"] != expected_stock:
                notes.append("stock and reservation records disagree")
            if effects and (effects[0]["item_id"] != first["json"]["item_id"] or
                            effects[0]["quantity"] != first["json"]["quantity"]):
                notes.append("wrong reservation effect")
    if task_id == "E7":
        for public, response in zip(requests, responses):
            if response["status"] == 200:
                key = public["path"].split("/")[-1]
                if snapshot["objects"].get(key, {}).get("hex") != public["json"]["content"].encode().hex():
                    notes.append("stored object differs from successful public write")
    if task_id == "E8" and responses and responses[-1]["status"] == 200:
        public = requests[-1]
        user = public["path"].split("/")[-1]
        expected = {"language": "en", "email_notifications": True, **public["json"]}
        if not matches(snapshot["preferences"].get(user), expected):
            notes.append("stored preferences do not implement full replacement")
    success = not notes
    outcome = "resilient_success" if success and all(r["status"] == 200 for r in responses) else "safe_failure"
    if not success:
        outcome = "unsafe_failure" if notes else "availability_failure"
        if all(r.get("status", 0) >= 400 for r in responses) and not snapshot.get("effects") and not snapshot.get("contract_violations"):
            outcome = "availability_failure"
    return {"pass": success, "outcome_class": outcome, "notes": list(dict.fromkeys(notes))}
