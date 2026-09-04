from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

import httpx

from benchmark.emulator import DeterministicDependency
from benchmark.fixtures.common import AppSettings
from benchmark.fixtures.t1 import create_app as create_t1
from benchmark.fixtures.t4 import create_app as create_t4
from benchmark.metrics import summarize
from benchmark.oracle import classify
from benchmark.scenarios import T1_SCENARIOS, T4_SCENARIOS
from benchmark.types import Observation


async def run_probe(task: str, fixture: str, scenario: str, app_factory=None) -> Observation:
    scripts = T1_SCENARIOS if task == "T1" else T4_SCENARIOS
    emulator = DeterministicDependency(scripts[scenario])
    settings = AppSettings()
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
    started = perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://artifact.test") as client:
            response = await asyncio.wait_for(client.request(method, path), timeout=settings.deadline_s)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = response.text
    except Exception as exc:  # harness must record artifact crashes, not crash itself
        exception = f"{type(exc).__name__}: {exc}"
    latency = perf_counter() - started
    deadline_violated = emulator.virtual_time_s > settings.deadline_s or latency > settings.deadline_s
    state = {} if task == "T1" else dict(app.state.orders.get("order-1", {}))
    outcome, notes = classify(task, scenario, status, body, len(emulator.attempts), deadline_violated,
                              exception, emulator.side_effects, state)
    return Observation(task, fixture, scenario, outcome, status, body, latency,
                       emulator.attempts, deadline_violated, exception,
                       list(emulator.side_effects), state, notes)


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
