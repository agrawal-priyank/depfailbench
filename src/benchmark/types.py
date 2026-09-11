from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class OutcomeClass(StrEnum):
    RESILIENT_SUCCESS = "resilient_success"
    SAFE_FAILURE = "safe_failure"
    UNSAFE_FAILURE = "unsafe_failure"
    AVAILABILITY_FAILURE = "availability_failure"


@dataclass(frozen=True)
class FaultStep:
    status: int | None = None
    json_body: Any = None
    raw_body: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    commits: bool = False
    delay_s: float = 0.0


@dataclass
class Attempt:
    index: int
    started_s: float
    completed_s: float
    method: str
    path: str
    status: int | None
    error: str | None
    idempotency_key: str | None


@dataclass
class Observation:
    task: str
    fixture: str
    scenario: str
    outcome_class: OutcomeClass
    response_status: int | None
    response_json: Any
    latency_s: float
    attempts: list[Attempt]
    deadline_violated: bool
    unhandled_exception: str | None
    side_effects: list[dict[str, Any]]
    final_state: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    @property
    def retry_amplification_factor(self) -> float:
        logical_operations = 1
        return len(self.attempts) / logical_operations

    @property
    def duplicate_side_effects(self) -> int:
        return max(0, len(self.side_effects) - 1)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retry_amplification_factor"] = self.retry_amplification_factor
        result["duplicate_side_effects"] = self.duplicate_side_effects
        return result
