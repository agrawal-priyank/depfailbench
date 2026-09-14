"""Behavioral check for finite per-attempt dependency timeouts."""

from __future__ import annotations

import asyncio
import json
import math
from time import perf_counter

import httpx

from benchmark.fixtures.common import AppSettings
from benchmark.full_tasks import CONTENT, KEY
from benchmark.normalization import normalize_state


class HangingDependency(httpx.AsyncBaseTransport):
    """A dependency that completes only when a bounded timeout interrupts it."""

    def __init__(self, task: str, settings: AppSettings):
        self.task = task
        self.settings = settings
        self.attempts: list[dict] = []
        self.contract_violations: list[str] = []

    @property
    def timeout_limit_s(self) -> float:
        # T2/T5 explicitly prescribe settings.timeout_s. T1/T4 prescribe a
        # finite per-attempt timeout within the whole-request deadline.
        if self.task in {"T2", "T5"}:
            return self.settings.timeout_s + 0.05
        return self.settings.deadline_s

    def _request_violation(self, request: httpx.Request, body: bytes) -> str | None:
        if self.task == "T1":
            if request.method != "GET" or request.url.path != "/products/7":
                return "T1 dependency request must be GET /products/7"
        elif self.task == "T2":
            if (
                request.method != "GET"
                or request.url.path != "/pages"
                or request.url.params.get("cursor") != "0"
            ):
                return "T2 first dependency request must be GET /pages?cursor=0"
        elif self.task == "T4":
            try:
                payload = json.loads(body) if body else None
            except (TypeError, ValueError, UnicodeDecodeError):
                payload = None
            if request.method != "POST" or request.url.path != "/charges":
                return "T4 dependency request must be POST /charges"
            if not isinstance(payload, dict) or payload.get("order_id") != "order-1":
                return "T4 charge payload must contain order_id=order-1"
        elif self.task == "T5":
            if request.method != "PUT" or request.url.path != f"/objects/{KEY}":
                return f"T5 dependency request must be PUT /objects/{KEY}"
            if body != CONTENT:
                return "T5 dependency request must preserve the exact supplied bytes"
        return None

    @staticmethod
    def _timeout_values(request: httpx.Request) -> list[float] | None:
        config = request.extensions.get("timeout")
        if not isinstance(config, dict) or not config:
            return None
        values = list(config.values())
        if not all(
            type(value) in {int, float} and math.isfinite(value) and value > 0
            for value in values
        ):
            return None
        return [float(value) for value in values]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        violation = self._request_violation(request, body)
        if violation:
            self.contract_violations.append(violation)
            self.attempts.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "timeout_mode": "contract_violation",
                    "bounded": False,
                }
            )
            return httpx.Response(400, json={"detail": "invalid dependency request"}, request=request)

        timeout_values = self._timeout_values(request)
        if timeout_values and max(timeout_values) <= self.timeout_limit_s:
            observed = max(timeout_values)
            self.attempts.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "timeout_mode": "httpx_configuration",
                    "observed_timeout_s": observed,
                    "simulated_timeout_s": observed,
                    "bounded": True,
                }
            )
            raise httpx.ReadTimeout("scripted hanging dependency", request=request)

        started = perf_counter()
        try:
            await asyncio.sleep(self.settings.deadline_s * 2)
        except asyncio.CancelledError:
            observed = perf_counter() - started
            # Cancellation at the evaluator's own whole-request deadline is a
            # watchdog intervention, not evidence that the generated client
            # configured a per-attempt timeout.  Leave a small separation from
            # that boundary so scheduler jitter cannot flip the classification.
            bounded = observed <= max(0.0, self.timeout_limit_s - 0.01)
            self.attempts.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "timeout_mode": "external_cancellation",
                    "observed_timeout_s": observed,
                    "bounded": bounded,
                }
            )
            raise
        self.attempts.append(
            {
                "method": request.method,
                "path": request.url.path,
                "timeout_mode": "none",
                "observed_timeout_s": self.settings.deadline_s * 2,
                "bounded": False,
            }
        )
        return httpx.Response(504, json={"detail": "dependency timed out"}, request=request)


async def evaluate_timeout_guard(task: str, factory) -> dict:
    settings = AppSettings()
    dependency = HangingDependency(task, settings)
    app = factory(dependency, settings)
    status = None
    body = None
    error = None
    state = {}
    started = perf_counter()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://artifact.test",
            ) as client:
                if task == "T1":
                    response = await asyncio.wait_for(
                        client.get("/products/7"), settings.deadline_s
                    )
                elif task == "T2":
                    response = await asyncio.wait_for(client.get("/catalog"), settings.deadline_s)
                elif task == "T4":
                    response = await asyncio.wait_for(
                        client.post("/orders/order-1/pay"), settings.deadline_s
                    )
                else:
                    response = await asyncio.wait_for(
                        client.post(
                            f"/uploads/{KEY}",
                            json={"content": CONTENT.decode("utf-8")},
                        ),
                        settings.deadline_s,
                    )
            status = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = response.text
            if task == "T4":
                orders = getattr(app.state, "orders", {})
                raw_state = orders.get("order-1") if hasattr(orders, "get") else None
                state = normalize_state(raw_state)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = perf_counter() - started
    simulated_dependency_time = sum(
        float(attempt.get("simulated_timeout_s", 0.0))
        for attempt in dependency.attempts
    )
    effective_elapsed = elapsed + simulated_dependency_time

    explicit_safe_failure = status is not None and 400 <= status < 600
    bounded_attempts = (
        1 <= len(dependency.attempts) <= settings.max_attempts
        and all(attempt.get("bounded") for attempt in dependency.attempts)
    )
    state_safe = task != "T4" or state.get("status") == "UNRESOLVED"
    passed = bool(
        error is None
        and effective_elapsed <= settings.deadline_s
        and explicit_safe_failure
        and bounded_attempts
        and state_safe
        and not dependency.contract_violations
    )
    return {
        "pass": passed,
        "response_status": status,
        "response_json": body,
        "unhandled_exception": error,
        "wall_latency_s": elapsed,
        "simulated_dependency_time_s": simulated_dependency_time,
        "effective_latency_s": effective_elapsed,
        "attempts": dependency.attempts,
        "contract_violations": sorted(set(dependency.contract_violations)),
        "notes": [] if passed else ["finite per-attempt timeout guard failed"],
    }
