"""Observable in-process dependency; scripted latency consumes real time."""

from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import json
import math
from time import monotonic

import httpx

from .contracts import Settings, TASKS, catalog_items, events, public_requests, quotes


class Dependency(httpx.AsyncBaseTransport):
    def __init__(self, task_id: str, scenario: str, settings: Settings):
        self.task_id, self.scenario, self.settings = task_id, scenario, settings
        self.public_index = 0
        self.created_at = monotonic()
        self.public_started = None
        self.attempts: list[dict] = []
        self.violations: list[str] = []
        self.counts: Counter = Counter()
        self.effects: list[dict] = []
        self.receipts: dict[str, dict] = {}
        self.identities: dict[str, dict] = {}
        self.stock = {"widget": 10, "gadget": 8}
        self.objects: dict[str, bytes] = {}
        self.preferences: dict[str, dict] = {}
        self.event_sink = None

    def emit(self):
        if self.event_sink is not None:
            self.event_sink(self.snapshot())

    @property
    def public(self):
        return public_requests(self.task_id, self.scenario)[self.public_index]

    def _check(self, request: httpx.Request, body: bytes) -> tuple[str, dict | None]:
        task = self.task_id
        try:
            payload = json.loads(body) if body else None
        except (ValueError, UnicodeDecodeError):
            payload = None
        method, path = request.method, request.url.path
        public = self.public
        if request.url.host != "dependency.test":
            return "wrong dependency host", payload
        if task == "E1":
            valid = method == "GET" and path == public["path"]
        elif task == "E2":
            valid = method == "GET" and path == "/quotes" and dict(request.url.params) == {
                "destination": public["json"]["destination"], "weight_g": str(public["json"]["weight_g"])}
        elif task in {"E3", "E4"}:
            valid = (method == "GET" and path == ("/pages" if task == "E3" else "/activity/pages")
                     and request.url.params.get("cursor") in {"0", "page-B", "end-C"})
        elif task == "E5":
            valid = method == "POST" and path == "/charges" and payload == {
                "order_id": public["path"].split("/")[2]}
        elif task == "E6":
            valid = method == "POST" and path == "/reservations" and payload == public["json"]
            if request.headers.get("Idempotency-Key") != public["path"].split("/")[-1]:
                self.violations.append("reservation identity must equal public request_id")
        elif task == "E7":
            key = public["path"].split("/")[-1]
            valid = method == "PUT" and path == f"/objects/{key}" and body == public["json"]["content"].encode()
        else:
            complete = {"language": "en", "email_notifications": True, **public["json"]}
            valid = method == "PUT" and path == public["path"] and payload == complete
        return ("" if valid else "downstream method/path/payload differs from the common contract"), payload

    def _commit(self, request: httpx.Request, body: bytes, payload: dict | None):
        task = self.task_id
        if task == "E5":
            order = payload["order_id"]
            key = request.headers.get("Idempotency-Key")
            identity = key or f"unkeyed-{len(self.effects)}"
            if identity in self.receipts:
                if self.identities[identity] != payload:
                    return 409, {"detail": "identity conflict"}
                return 200, self.receipts[identity]
            receipt = {"charge_id": f"charge-{len(self.effects)+1}", "status": "captured"}
            self.identities[identity] = payload
            self.receipts[identity] = receipt
            self.effects.append({"kind": "charge", "order_id": order, **receipt})
            return 200, receipt
        if task == "E6":
            identity = request.headers.get("Idempotency-Key") or f"unkeyed-{len(self.effects)}"
            if identity in self.receipts:
                if self.identities[identity] != payload:
                    return 409, {"detail": "identity conflict"}
                return 200, self.receipts[identity]
            item, quantity = payload["item_id"], payload["quantity"]
            if self.stock.get(item, 0) < quantity:
                return 409, {"detail": "insufficient stock"}
            self.stock[item] -= quantity
            receipt = {"reservation_id": f"reservation-{len(self.effects)+1}",
                       "request_id": identity, "item_id": item, "quantity": quantity, "status": "reserved"}
            self.identities[identity] = dict(payload)
            self.receipts[identity] = receipt
            self.effects.append({"kind": "reservation", **receipt})
            return 200, receipt
        if task == "E7":
            key = request.url.path.split("/")[-1]
            self.objects[key] = body
            digest = hashlib.sha256(body).hexdigest()
            self.effects.append({"kind": "write", "key": key, "sha256": digest})
            return 200, {"key": key, "sha256": digest}
        user = request.url.path.split("/")[-1]
        self.preferences[user] = dict(payload)
        self.effects.append({"kind": "preferences", "user_id": user, "preferences": dict(payload)})
        return 200, {"user_id": user, "preferences": dict(payload)}

    def _read(self, request: httpx.Request):
        scenario, task = self.scenario, self.task_id
        if task == "E1":
            if scenario == "not_found":
                return 404, {"detail": "not found"}
            product = int(request.url.path.split("/")[-1])
            return 200, {"id": product + (1 if scenario == "wrong_identity" else 0),
                         "name": "Keyboard" if product == 7 else "Mouse",
                         "price": 49.5 if product == 7 else 12.0}
        if task == "E2":
            return 200, {"quotes": quotes(scenario)}
        index = ["0", "page-B", "end-C"].index(request.url.params["cursor"])
        rows = catalog_items(scenario) if task == "E3" else events(scenario)
        if scenario in {"identical_overlap", "conflicting_duplicate"} and rows:
            rows = [*rows[:2], dict(rows[0]), *rows[3:]]
            if scenario == "conflicting_duplicate":
                rows[2]["name" if task == "E3" else "user_id"] = "conflicting"
        if not rows:
            return 200, {"items" if task == "E3" else "events": [], "next_cursor": None}
        cursor = ["page-B", "end-C", None][index]
        if scenario == "cursor_cycle" and index == 1:
            cursor = "page-B"
        return 200, {"items" if task == "E3" else "events": rows[index*2:index*2+2], "next_cursor": cursor}

    async def _wait(self, request: httpx.Request, delay: float):
        config = request.extensions.get("timeout")
        values = list(config.values()) if isinstance(config, dict) else []
        finite = bool(values) and all(type(x) in {int, float} and math.isfinite(x) and x > 0
                                      for x in values)
        if not finite or max(values) > self.settings.timeout_s + 1e-6:
            self.violations.append("finite per-attempt timeout must not exceed settings.timeout_s")
        timeout = config.get("read") if isinstance(config, dict) else None
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
            await asyncio.sleep(min(delay, timeout))
            if delay >= timeout:
                raise httpx.ReadTimeout("scripted dependency timeout", request=request)
        else:
            await asyncio.sleep(delay)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        violation, payload = self._check(request, body)
        operation = request.url.params.get("cursor") or request.url.path
        key = (self.public_index, operation)
        self.counts[key] += 1
        attempt = self.counts[key]
        start = monotonic()
        origin = self.public_started if self.public_started is not None else self.created_at
        timing_origin = "public_request" if self.public_started is not None else "dependency_initialization"
        previous = next((r for r in reversed(self.attempts) if r["public_index"] == self.public_index
                         and r["timing_origin"] == timing_origin), None)
        row = {"public_index": self.public_index, "operation": operation, "attempt": attempt,
               "method": request.method, "path": request.url.path, "query": dict(request.url.params),
               "payload": payload, "body_sha256": hashlib.sha256(body).hexdigest(),
               "idempotency_key": request.headers.get("Idempotency-Key"),
               "timeout_config": request.extensions.get("timeout"), "status": None,
               "timing_origin": timing_origin,
               "started_offset_s": start-origin,
               "gap_since_previous_attempt_end_s": max(0.0, start-origin-previous["finished_offset_s"])
                   if previous and "finished_offset_s" in previous else None}
        self.attempts.append(row)
        self.emit()
        try:
            if violation:
                self.violations.append(violation)
                status, data = 400, {"detail": "invalid dependency request"}
            else:
                if attempt > self.settings.max_attempts:
                    self.violations.append("logical-operation attempt budget exceeded")
                mode = self.scenario
                if TASKS[self.task_id].pattern == "pages" and operation != "page-B" and mode in COMMON_MIDDLE_FAULTS:
                    mode = "clean"
                headers = {}
                delay = 0.002
                if mode == "hanging_dependency":
                    delay = self.settings.deadline_s*3 + self.settings.timeout_s
                elif mode in {"timeout_before_commit", "committed_response_lost"} and attempt == 1:
                    if mode == "committed_response_lost":
                        self._commit(request, body, payload)
                        self.emit()
                    delay = self.settings.deadline_s*3 + self.settings.timeout_s
                elif mode == "cumulative_budget":
                    delay = self.settings.timeout_s * 0.8
                await self._wait(request, delay)
                if mode == "persistent_503" or (mode == "transient_503" and attempt <= 2):
                    status, data = 503, {"detail": "unavailable"}
                elif mode == "cumulative_budget" and attempt == 1:
                    status, data = 503, {"detail": "transient"}
                elif mode == "retry_after_exceeds_deadline" or (mode == "rate_limit" and attempt == 1):
                    status, data = 429, {"detail": "rate limited"}
                    headers["Retry-After"] = str(self.settings.deadline_s + 1) if mode == "retry_after_exceeds_deadline" else "0"
                elif TASKS[self.task_id].pattern in {"action", "write"}:
                    status, data = self._commit(request, body, payload)
                else:
                    status, data = self._read(request)
                if mode == "malformed_200" and status == 200:
                    data = {"malformed": True}
                row["status"] = status
                return httpx.Response(status, json=data, headers=headers, request=request)
            row["status"] = status
            return httpx.Response(status, json=data, request=request)
        except BaseException as exc:
            row["exception"] = type(exc).__name__
            raise
        finally:
            finished = monotonic()
            row["elapsed_s"] = finished - start
            row["finished_offset_s"] = finished-origin
            self.emit()

    def snapshot(self) -> dict:
        return {"attempts": self.attempts, "contract_violations": self.violations,
                "effects": self.effects, "stock": self.stock,
                "objects": {key: {"sha256": hashlib.sha256(body).hexdigest(), "hex": body.hex()}
                            for key, body in self.objects.items()}, "preferences": self.preferences}


COMMON_MIDDLE_FAULTS = frozenset({"transient_503", "persistent_503", "timeout_before_commit",
                                "hanging_dependency", "rate_limit", "retry_after_exceeds_deadline",
                                "malformed_200"})
