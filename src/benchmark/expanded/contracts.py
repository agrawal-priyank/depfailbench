"""Fixed, inspectable task inputs and scenario expectations for local validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    downstream_url: str = "http://dependency.test"
    timeout_s: float = 0.25
    max_attempts: int = 3
    deadline_s: float = 1.0


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    historical_id: str | None
    pattern: str
    method: str
    path: str
    body: dict | None = None


TASKS = {
    "E1": Task("E1", "Product proxy", "T1", "read", "GET", "/products/7"),
    "E2": Task("E2", "Shipping-quote selection", None, "read", "POST", "/shipping/quote",
               {"destination": "Boston", "weight_g": 500}),
    "E3": Task("E3", "Paginated catalog", "T2", "pages", "GET", "/catalog"),
    "E4": Task("E4", "Paginated activity summary", None, "pages", "GET", "/activity/failed-logins"),
    "E5": Task("E5", "Order/payment", "T4", "action", "POST", "/orders/order-1/pay"),
    "E6": Task("E6", "Inventory reservation", None, "action", "POST", "/reservations/request-1",
               {"item_id": "widget", "quantity": 3}),
    "E7": Task("E7", "Object upload", "T5", "write", "POST", "/uploads/sample.txt",
               {"content": "benchmark-content-expanded"}),
    "E8": Task("E8", "User-preferences replacement", None, "write", "PUT", "/preferences/alice",
               {"language": "es", "email_notifications": False}),
}

COMMON_FAULTS = (
    "transient_503", "persistent_503", "timeout_before_commit", "hanging_dependency",
    "rate_limit", "retry_after_exceeds_deadline", "malformed_200",
)
RECOVERY = frozenset({"clean", "alternate_clean", "transient_503", "timeout_before_commit",
                      "rate_limit", "committed_response_lost", "repeated_request",
                      "identical_overlap", "preference_replacement"})
SAFE_UNAVAILABLE = frozenset({"persistent_503", "hanging_dependency", "retry_after_exceeds_deadline"})


def scenarios(task_id: str) -> tuple[str, ...]:
    task = TASKS[task_id]
    extra = ["alternate_clean", *COMMON_FAULTS]
    if task.pattern == "pages":
        extra += ["cursor_cycle", "conflicting_duplicate", "identical_overlap", "cumulative_budget"]
    if task.pattern in {"action", "write"}:
        extra += ["committed_response_lost", "repeated_request"]
    if task_id == "E1":
        extra += ["not_found", "wrong_identity"]
    if task_id == "E2":
        extra += ["quote_tie", "no_valid_quotes", "invalid_input", "conflicting_quote"]
    if task_id == "E4":
        extra += ["empty_history"]
    if task_id == "E6":
        extra += ["insufficient_stock", "conflicting_identity", "invalid_input"]
    if task_id == "E8":
        extra += ["preference_replacement", "invalid_input"]
    return ("clean", *extra)


def is_functional(scenario: str) -> bool:
    return scenario in {"clean", "alternate_clean", "quote_tie", "no_valid_quotes", "not_found",
                        "invalid_input", "empty_history", "insufficient_stock", "repeated_request",
                        "preference_replacement", "conflicting_identity", "identical_overlap"}


def public_requests(task_id: str, scenario: str) -> list[dict]:
    task = TASKS[task_id]
    request = {"method": task.method, "path": task.path, "json": task.body}
    if scenario == "alternate_clean":
        variants = {
            "E1": ("/products/19", None),
            "E2": (task.path, {"destination": "Seattle", "weight_g": 1200}),
            "E5": ("/orders/order-2/pay", None),
            "E6": ("/reservations/request-2", {"item_id": "gadget", "quantity": 2}),
            "E7": ("/uploads/another.txt", {"content": "different content: café"}),
            "E8": ("/preferences/bob", {"language": "fr", "email_notifications": True}),
        }
        if task_id in variants:
            request["path"], request["json"] = variants[task_id]
    if scenario == "invalid_input":
        request["json"] = {"E2": {"destination": "Boston", "weight_g": True},
                           "E6": {"item_id": "widget", "quantity": -1},
                           "E8": {"email_notifications": "false", "unexpected": 1}}[task_id]
    if scenario == "insufficient_stock":
        request["json"] = {"item_id": "widget", "quantity": 11}
    if scenario == "repeated_request":
        return [request, dict(request)]
    if scenario == "conflicting_identity":
        return [request, {**request, "json": {"item_id": "widget", "quantity": 4}}]
    if scenario == "preference_replacement":
        return [request, {**request, "json": {}}]
    return [request]


def catalog_items(scenario: str) -> list[dict]:
    start = 21 if scenario == "alternate_clean" else 1
    return [{"id": i, "name": f"Item {i}"} for i in range(start, start + 6)]


def events(scenario: str) -> list[dict]:
    if scenario == "empty_history":
        return []
    users = ["zoe", "amy", "zoe", "ben", "zoe", "amy"] if scenario == "alternate_clean" else ["alice", "bob", "alice", "bob", "alice", "alice"]
    return [{"event_id": f"event-{i}", "user_id": user, "event_type": "logout" if i == 4 else "login",
             "outcome": "success" if i == 3 else "failure"} for i, user in enumerate(users)]


def quotes(scenario: str) -> list[dict]:
    if scenario == "no_valid_quotes":
        return [{"quote_id": "invalid", "price_cents": True, "currency": "USD", "delivery_days": 2}]
    result = [
        {"quote_id": "slow", "price_cents": 700, "currency": "USD", "delivery_days": 5},
        {"quote_id": "cheap", "price_cents": 500, "currency": "USD", "delivery_days": 3},
        {"quote_id": "invalid", "price_cents": -1, "currency": "USD", "delivery_days": 1},
    ]
    if scenario == "quote_tie":
        result += [{"quote_id": "a", "price_cents": 500, "currency": "USD", "delivery_days": 2},
                   {"quote_id": "b", "price_cents": 500, "currency": "USD", "delivery_days": 2}]
    if scenario == "alternate_clean":
        result[1] = {"quote_id": "other", "price_cents": 450, "currency": "USD", "delivery_days": 4}
    if scenario == "conflicting_quote":
        result += [{**result[0], "price_cents": 1}]
    return result
