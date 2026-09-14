"""Full-study task fixtures. All contracts fixed before full-study generation."""

from __future__ import annotations

import hashlib
import math
from collections import Counter

import httpx
from fastapi import FastAPI, HTTPException

from benchmark.fixtures.common import AppSettings


ITEMS = [{"id": i, "name": f"Item {i}"} for i in range(1, 7)]
CONTENT = b"benchmark-content-v1"
KEY = "sample.txt"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
SCENARIOS = {
    "T2": (
        "clean",
        "transient_503",
        "persistent_503",
        "timeout",
        "rate_limit",
        "malformed_200",
        "cursor_cycle",
    ),
    "T5": (
        "clean",
        "transient_503",
        "persistent_503",
        "timeout_before_commit",
        "rate_limit",
        "malformed_200",
        "committed_response_lost",
    ),
}
SAFE = {"persistent_503", "rate_limit", "malformed_200", "cursor_cycle"}


class Dependency(httpx.AsyncBaseTransport):
    """Observable, deterministic dependency for the pagination and upload tasks."""

    def __init__(
        self,
        task: str,
        scenario: str,
        *,
        require_finite_timeout: bool = False,
        timeout_ceiling_s: float | None = None,
    ):
        self.task = task
        self.scenario = scenario
        self.require_finite_timeout = require_finite_timeout
        self.timeout_ceiling_s = timeout_ceiling_s
        self.attempts: list[dict] = []
        self.counts: Counter[str] = Counter()
        self.objects: dict[str, bytes] = {}
        self.virtual_time_s = 0.0
        self.writes: list[dict] = []
        self.contract_violations: list[str] = []

    def _invalid_request(
        self,
        request: httpx.Request,
        operation: str,
        message: str,
        timeout_config: dict[str, float | None] | None,
    ) -> httpx.Response:
        self.contract_violations.append(message)
        self.counts[operation] += 1
        self.virtual_time_s += 0.01
        self.attempts.append(
            {
                "operation": operation,
                "method": request.method,
                "path": request.url.path,
                "status": 400,
                "timeout": False,
                "request_valid": False,
                "timeout_config": timeout_config,
            }
        )
        return httpx.Response(
            400,
            json={"detail": "invalid dependency request"},
            request=request,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_body = await request.aread()
        timeout_config = request.extensions.get("timeout")
        timeout_config = dict(timeout_config) if isinstance(timeout_config, dict) else None

        if self.task == "T2":
            cursor = request.url.params.get("cursor")
            operation = cursor or request.url.path
            if (
                request.method != "GET"
                or request.url.path != "/pages"
                or cursor not in {"0", "1", "2"}
            ):
                return self._invalid_request(
                    request,
                    operation,
                    "T2 dependency request must be GET /pages with cursor 0, 1, or 2",
                    timeout_config,
                )
            fault = cursor == "1"
        else:
            operation = request.url.path
            if request.method != "PUT" or request.url.path != f"/objects/{KEY}":
                return self._invalid_request(
                    request,
                    operation,
                    f"T5 dependency request must be PUT /objects/{KEY}",
                    timeout_config,
                )
            if request_body != CONTENT:
                return self._invalid_request(
                    request,
                    operation,
                    "T5 dependency request must preserve the exact supplied bytes",
                    timeout_config,
                )
            fault = True

        if self.require_finite_timeout:
            values = list(timeout_config.values()) if timeout_config else []
            valid_timeout = bool(values) and all(
                type(value) in {int, float}
                and math.isfinite(value)
                and value > 0
                and (self.timeout_ceiling_s is None or value <= self.timeout_ceiling_s)
                for value in values
            )
            if not valid_timeout:
                return self._invalid_request(
                    request,
                    operation,
                    "dependency request must use settings.timeout_s as a finite upper bound",
                    timeout_config,
                )

        self.counts[operation] += 1
        attempt_number = self.counts[operation]
        mode = self.scenario if fault else "clean"
        status = 200
        timeout = False

        if mode == "transient_503" and attempt_number <= 2:
            status = 503
        if mode == "persistent_503":
            status = 503
        if mode == "rate_limit" and attempt_number == 1:
            status = 429
        if mode in {"timeout", "timeout_before_commit", "committed_response_lost"} and attempt_number == 1:
            timeout = True

        self.virtual_time_s += 0.25 if timeout else 0.01
        if self.task == "T2":
            index = int(operation)
            body = {
                "items": ITEMS[index * 2 : index * 2 + 2],
                "next_cursor": str(index + 1) if index < 2 else None,
            }
            if mode == "malformed_200":
                body = {"items": "invalid", "next_cursor": None}
            if mode == "cursor_cycle":
                body = {"items": ITEMS[2:4], "next_cursor": "1"}
        else:
            key = request.url.path[len("/objects/") :]
            commit = status == 200 and (not timeout or mode == "committed_response_lost")
            if commit:
                self.objects[key] = request_body
                self.writes.append(
                    {"key": key, "sha256": hashlib.sha256(request_body).hexdigest()}
                )
            body = {"key": key, "sha256": hashlib.sha256(request_body).hexdigest()}
            if mode == "malformed_200":
                body = {"key": key, "sha256": "invalid"}

        self.attempts.append(
            {
                "operation": operation,
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "timeout": timeout,
                "request_valid": True,
                "timeout_config": timeout_config,
            }
        )
        if timeout:
            raise httpx.ReadTimeout("scripted timeout", request=request)
        return httpx.Response(
            status,
            json=body if status == 200 else {},
            headers={"Retry-After": "0"},
            request=request,
        )


def create_reference(task, resilient, transport, settings=None):
    cfg = settings or AppSettings()
    app = FastAPI()

    async def fetch(client, method, path, **kwargs):
        for attempt in range(cfg.max_attempts if resilient else 1):
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.HTTPError:
                if resilient and attempt + 1 < cfg.max_attempts:
                    continue
                raise HTTPException(503, "unavailable")
            if (
                response.status_code in {429, 502, 503, 504}
                and resilient
                and attempt + 1 < cfg.max_attempts
            ):
                continue
            if response.status_code != 200:
                raise HTTPException(503, "unavailable")
            return response.json()
        raise HTTPException(503, "unavailable")

    if task == "T2":

        @app.get("/catalog")
        async def catalog():
            items = []
            cursor = "0"
            seen = set()
            async with httpx.AsyncClient(
                transport=transport,
                base_url=cfg.downstream_url,
                timeout=cfg.timeout_s,
            ) as client:
                while cursor is not None:
                    if cursor in seen or len(seen) >= 3:
                        raise HTTPException(502, "invalid cursor")
                    seen.add(cursor)
                    page = await fetch(client, "GET", "/pages", params={"cursor": cursor})
                    if resilient:
                        if (
                            not isinstance(page, dict)
                            or not isinstance(page.get("items"), list)
                            or not (
                                page.get("next_cursor") is None
                                or isinstance(page.get("next_cursor"), str)
                            )
                        ):
                            raise HTTPException(502, "invalid page")
                        if any(
                            not isinstance(item, dict)
                            or type(item.get("id")) is not int
                            or not isinstance(item.get("name"), str)
                            for item in page["items"]
                        ):
                            raise HTTPException(502, "invalid item")
                    items.extend(page["items"])
                    cursor = page["next_cursor"]
            return {"items": items}

    else:

        @app.post("/uploads/{object_key}")
        async def upload(object_key: str, payload: dict):
            content = payload["content"].encode()
            digest = hashlib.sha256(content).hexdigest()
            async with httpx.AsyncClient(
                transport=transport,
                base_url=cfg.downstream_url,
                timeout=cfg.timeout_s,
            ) as client:
                body = await fetch(client, "PUT", f"/objects/{object_key}", content=content)
            if resilient and body != {"key": object_key, "sha256": digest}:
                raise HTTPException(502, "invalid receipt")
            return body

    return app


def _attempt_signature(attempt: dict) -> tuple[int | str | None, bool]:
    if attempt.get("timeout"):
        return "timeout", True
    return attempt.get("status"), False


def _valid_t2_success_trace(scenario: str, attempts: list[dict]) -> bool:
    """Require successful catalogs to be supported by the scripted page trace."""

    if scenario in {"persistent_503", "malformed_200", "cursor_cycle"}:
        return False
    by_cursor = {cursor: [] for cursor in ("0", "1", "2")}
    ranks = []
    for attempt in attempts:
        operation = attempt.get("operation")
        if operation not in by_cursor or not attempt.get("request_valid", True):
            return False
        by_cursor[operation].append(_attempt_signature(attempt))
        ranks.append(int(operation))
    if ranks != sorted(ranks):
        return False

    expected_middle = {
        "clean": [(200, False)],
        "transient_503": [(503, False), (503, False), (200, False)],
        "timeout": [("timeout", True), (200, False)],
        "rate_limit": [(429, False), (200, False)],
    }.get(scenario)
    return (
        expected_middle is not None
        and by_cursor["0"] == [(200, False)]
        and by_cursor["1"] == expected_middle
        and by_cursor["2"] == [(200, False)]
    )


def _has_confirmed_success(attempts: list[dict]) -> bool:
    return bool(
        attempts
        and attempts[-1].get("status") == 200
        and not attempts[-1].get("timeout")
        and attempts[-1].get("request_valid", True)
    )


def _valid_catalog_body(body) -> bool:
    return (
        isinstance(body, dict)
        and body == {"items": ITEMS}
        and all(
            isinstance(item, dict)
            and type(item.get("id")) is int
            and isinstance(item.get("name"), str)
            for item in body["items"]
        )
    )


def classify(task, scenario, status, body, exception, deadline, dep):
    if exception or deadline:
        return "availability_failure"
    if task == "T5" and len(dep.attempts) > 3:
        return "availability_failure"
    if any(attempts > 3 for attempts in dep.counts.values()):
        return "availability_failure"
    if dep.contract_violations:
        return "unsafe_failure"

    if task == "T2":
        if status == 200 and _valid_catalog_body(body):
            if _valid_t2_success_trace(scenario, dep.attempts):
                return "resilient_success"
            return "unsafe_failure"
        if status is not None and 400 <= status < 600:
            return "safe_failure"
        return "unsafe_failure"

    if any(key != KEY or value != CONTENT for key, value in dep.objects.items()):
        return "unsafe_failure"
    if (
        status == 200
        and body == {"key": KEY, "sha256": DIGEST}
        and dep.objects.get(KEY) == CONTENT
    ):
        if scenario == "malformed_200" or not _has_confirmed_success(dep.attempts):
            return "unsafe_failure"
        return "resilient_success"
    if status is not None and 400 <= status < 600:
        return "safe_failure"
    return "unsafe_failure"
