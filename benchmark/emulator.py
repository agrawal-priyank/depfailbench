from __future__ import annotations

import json
from collections import defaultdict
from time import monotonic
from typing import Any

import httpx

from benchmark.types import Attempt, FaultStep


class DeterministicDependency(httpx.AsyncBaseTransport):
    """Scripted downstream with a virtual clock and payment idempotency."""

    def __init__(self, steps: list[FaultStep], *, step_duration_s: float = 0.01):
        if not steps:
            raise ValueError("at least one fault step is required")
        self.steps = steps
        self.step_duration_s = step_duration_s
        self.attempts: list[Attempt] = []
        self.side_effects: list[dict[str, Any]] = []
        self._responses_by_key: dict[str, dict[str, Any]] = {}
        self._calls_by_path: dict[str, int] = defaultdict(int)
        self._virtual_time = 0.0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        index = len(self.attempts)
        step = self.steps[min(index, len(self.steps) - 1)]
        started = self._virtual_time
        self._virtual_time += self.step_duration_s + step.delay_s
        key = request.headers.get("Idempotency-Key")
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
                                     request.url.path, status, error, key))
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
