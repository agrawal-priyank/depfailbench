from __future__ import annotations

import json
import math
from collections import defaultdict
from time import monotonic
from typing import Any

import httpx

from benchmark.types import Attempt, FaultStep


class DeterministicDependency(httpx.AsyncBaseTransport):
    """Scripted downstream with a virtual clock and payment idempotency."""

    def __init__(
        self,
        steps: list[FaultStep],
        *,
        task: str | None = None,
        require_finite_timeout: bool = False,
        timeout_ceiling_s: float | None = None,
        step_duration_s: float = 0.01,
    ):
        if not steps:
            raise ValueError("at least one fault step is required")
        self.steps = steps
        self.task = task
        self.require_finite_timeout = require_finite_timeout
        self.timeout_ceiling_s = timeout_ceiling_s
        self.step_duration_s = step_duration_s
        self.attempts: list[Attempt] = []
        self.side_effects: list[dict[str, Any]] = []
        self.contract_violations: list[str] = []
        self._responses_by_key: dict[str, dict[str, Any]] = {}
        self._calls_by_path: dict[str, int] = defaultdict(int)
        self._virtual_time = 0.0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        index = len(self.attempts)
        step = self.steps[min(index, len(self.steps) - 1)]
        started = self._virtual_time
        request_body = await request.aread()
        timeout_config = request.extensions.get("timeout")
        timeout_config = dict(timeout_config) if isinstance(timeout_config, dict) else None
        key = request.headers.get("Idempotency-Key")
        violation = None
        if self.task == "T1":
            if request.method != "GET" or request.url.path != "/products/7":
                violation = "T1 dependency request must be GET /products/7"
        elif self.task == "T4":
            payload = None
            try:
                payload = json.loads(request_body) if request_body else None
            except (TypeError, ValueError, UnicodeDecodeError):
                pass
            if request.method != "POST" or request.url.path != "/charges":
                violation = "T4 dependency request must be POST /charges"
            elif not isinstance(payload, dict) or payload.get("order_id") != "order-1":
                violation = "T4 charge payload must contain order_id=order-1"
        if violation is None and self.require_finite_timeout:
            values = list(timeout_config.values()) if timeout_config else []
            valid_timeout = bool(values) and all(
                type(value) in {int, float}
                and math.isfinite(value)
                and value > 0
                and (self.timeout_ceiling_s is None or value <= self.timeout_ceiling_s)
                for value in values
            )
            if not valid_timeout:
                violation = "dependency request must configure finite bounded timeouts"
        if violation:
            self.contract_violations.append(violation)
            self._virtual_time += self.step_duration_s
            completed = self._virtual_time
            self.attempts.append(Attempt(index + 1, started, completed, request.method,
                                         request.url.path, 400, None, key, timeout_config))
            return httpx.Response(400, json={"detail": "invalid dependency request"}, request=request)

        self._virtual_time += self.step_duration_s + step.delay_s
        status = step.status
        error = step.error
        response_body = step.json_body

        if request.method == "POST" and request.url.path == "/charges":
            if key and key in self._responses_by_key:
                status, response_body, error = 200, self._responses_by_key[key], None
            elif step.commits:
                charge = {"charge_id": f"ch_{len(self.side_effects)+1}", "status": "captured"}
                self.side_effects.append({**charge, "idempotency_key": key})
                if key:
                    self._responses_by_key[key] = charge
                response_body = charge

        completed = self._virtual_time
        self.attempts.append(Attempt(index + 1, started, completed, request.method,
                                     request.url.path, status, error, key, timeout_config))
        self._calls_by_path[request.url.path] += 1
        if error == "timeout":
            raise httpx.ReadTimeout("scripted response loss/timeout", request=request)
        if error == "connect":
            raise httpx.ConnectError("scripted connection failure", request=request)
        content = step.raw_body
        if content is None:
            content = json.dumps(response_body).encode() if response_body is not None else b""
        return httpx.Response(status or 500, headers=step.headers, content=content, request=request)

    @property
    def virtual_time_s(self) -> float:
        return self._virtual_time
