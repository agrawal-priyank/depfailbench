"""Public API for adding task-specific behavioral contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI

from benchmark.fixtures.common import AppSettings

TASK_API_VERSION = 1
OUTCOMES = frozenset(
    {"resilient_success", "safe_failure", "unsafe_failure", "availability_failure"}
)


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    accepted_outcomes: frozenset[str]
    clean: bool = False


@dataclass(frozen=True)
class TimeoutGuardPolicy:
    required_conditions: frozenset[str]
    timeout_limit: str = "request_deadline"
    tolerance_s: float = 0.05


class TaskAdapter(ABC):
    """Trusted executable contract supplied by a benchmark task author."""

    api_version = TASK_API_VERSION
    task_id: str
    display_name: str
    scenarios: tuple[ScenarioSpec, ...]
    timeout_guard: TimeoutGuardPolicy | None = None

    @abstractmethod
    def make_dependency(self, scenario_id: str, settings: AppSettings) -> httpx.AsyncBaseTransport:
        pass

    @abstractmethod
    async def invoke(self, client: httpx.AsyncClient, settings: AppSettings) -> httpx.Response:
        pass

    @abstractmethod
    def inspect_dependency_request(
        self, request: httpx.Request, body: bytes, scenario_id: str
    ) -> str | None:
        """Return an exact contract violation, or ``None`` when valid."""

    @abstractmethod
    def snapshot_dependency(self, dependency: httpx.AsyncBaseTransport) -> dict[str, Any]:
        pass

    def snapshot_state(
        self, app: FastAPI, dependency: httpx.AsyncBaseTransport
    ) -> dict[str, Any]:
        return {}

    @abstractmethod
    def classify(self, scenario_id: str, evidence: dict[str, Any]) -> tuple[str, list[str]]:
        pass

    def timeout_failure_is_safe(self, evidence: dict[str, Any]) -> bool:
        status = evidence.get("response_status")
        return status is not None and 400 <= status < 600


def validate_adapter(adapter: TaskAdapter) -> None:
    if adapter.api_version != TASK_API_VERSION:
        raise ValueError(f"unsupported task API version: {adapter.api_version}")
    if not adapter.task_id or not adapter.scenarios:
        raise ValueError("adapter needs a task ID and scenarios")
    ids = [scenario.id for scenario in adapter.scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate scenario IDs for {adapter.task_id}")
    clean = [scenario for scenario in adapter.scenarios if scenario.clean]
    if len(clean) != 1 or not adapter.scenarios[0].clean:
        raise ValueError("exactly one clean scenario is required and it must be first")
    for scenario in adapter.scenarios:
        if not scenario.accepted_outcomes or not scenario.accepted_outcomes <= OUTCOMES:
            raise ValueError(f"invalid accepted outcomes for {adapter.task_id}/{scenario.id}")
