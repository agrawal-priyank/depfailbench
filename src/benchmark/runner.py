from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

import httpx

from benchmark.emulator import DeterministicDependency
from benchmark.fixtures.common import AppSettings
from benchmark.fixtures.t1 import create_app as create_t1
from benchmark.fixtures.t4 import create_app as create_t4
from benchmark.metrics import summarize
from benchmark.normalization import normalize_state
from benchmark.oracle import classify
from benchmark.scenarios import T1_SCENARIOS, T4_SCENARIOS
from benchmark.types import Observation, OutcomeClass


def _t1_success_has_valid_trace(scenario: str, attempts: list) -> bool:
    """Reject successful public responses that are unsupported by the dependency trace."""

    signature = [(attempt.status, attempt.error) for attempt in attempts]
    expected = {
        "clean": [(200, None)],
        "transient_503": [(503, None), (503, None), (200, None)],
        "rate_limit": [(429, None), (200, None)],
    }
    return scenario in expected and signature == expected[scenario]


def _has_confirmed_dependency_success(attempts: list) -> bool:
    return bool(attempts and attempts[-1].status == 200 and attempts[-1].error is None)


async def run_probe(
    task: str,
    fixture: str,
    scenario: str,
    app_factory=None,
    *,
    condition: str | None = None,
) -> Observation:
    scripts = T1_SCENARIOS if task == "T1" else T4_SCENARIOS
    settings = AppSettings()
    emulator = DeterministicDependency(
        scripts[scenario],
        task=task,
    )
    app = (
        app_factory(emulator, settings)
        if app_factory
        else (create_t1 if task == "T1" else create_t4)(fixture, emulator, settings)
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    path = "/products/7" if task == "T1" else "/orders/order-1/pay"
    method = "GET" if task == "T1" else "POST"
    status = None
    body = None
    exception = None
    latency = 0.0
    state = {}
    try:
        # ASGITransport does not drive startup/shutdown. Support both event
        # handlers and lifespan contexts without changing generated code.
        async with app.router.lifespan_context(app):
            started = perf_counter()
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://artifact.test") as client:
                    response = await asyncio.wait_for(client.request(method, path), timeout=settings.deadline_s)
                status = response.status_code
                try:
                    body = response.json()
                except ValueError:
                    body = response.text
            except Exception as exc:
                exception = f"{type(exc).__name__}: {exc}"
            finally:
                latency = perf_counter() - started
                if task == "T1":
                    state = {}
                else:
                    orders = getattr(app.state, "orders", {})
                    raw_state = orders.get("order-1") if isinstance(orders, Mapping) else None
                    state = normalize_state(raw_state)
    except Exception as exc:
        exception = f"{type(exc).__name__}: {exc}"
    # The transport advances a virtual dependency clock rather than sleeping.
    # Add that simulated service time to real application/backoff time so the
    # end-to-end deadline cannot be evaded by splitting work across both clocks.
    effective_latency = latency + emulator.virtual_time_s
    deadline_violated = effective_latency > settings.deadline_s
    outcome, notes = classify(task, scenario, status, body, len(emulator.attempts), deadline_violated,
                              exception, emulator.side_effects, state)
    if emulator.contract_violations:
        outcome = OutcomeClass.UNSAFE_FAILURE
        notes.extend(sorted(set(emulator.contract_violations)))
    elif outcome == OutcomeClass.RESILIENT_SUCCESS and task == "T1" and not _t1_success_has_valid_trace(
        scenario, emulator.attempts
    ):
        outcome = OutcomeClass.UNSAFE_FAILURE
        notes.append("public success is unsupported by the required dependency trace")
    elif outcome == OutcomeClass.RESILIENT_SUCCESS and task == "T4" and not _has_confirmed_dependency_success(
        emulator.attempts
    ):
        outcome = OutcomeClass.UNSAFE_FAILURE
        notes.append("payment success lacks a confirmed provider response")
    return Observation(task, fixture, scenario, outcome, status, body, latency,
                       emulator.attempts, deadline_violated, exception,
                       list(emulator.side_effects), state, notes,
                       wall_latency_s=latency,
                       virtual_dependency_time_s=emulator.virtual_time_s,
                       effective_latency_s=effective_latency)


async def run_matrix(repetitions: int = 3) -> list[Observation]:
    observations = []
    for _ in range(repetitions):
        for task, scenarios in (("T1", T1_SCENARIOS), ("T4", T4_SCENARIOS)):
            for fixture in ("reference_naive", "reference_resilient"):
                for scenario in scenarios:
                    observations.append(await run_probe(task, fixture, scenario))
    return observations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("results/reference_validation.jsonl"))
    args = parser.parse_args()
    rows = asyncio.run(run_matrix(args.repetitions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row.to_dict()) + "\n" for row in rows))
    print(f"wrote {len(rows)} observations to {args.output}")
    print(json.dumps(summarize(rows), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
