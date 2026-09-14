"""Task-agnostic evaluator for manifest-registered adapters."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import random
import sys
import time
from pathlib import Path

import httpx

from benchmark.fixtures.common import AppSettings
from benchmark.full_eval import evaluation_seed
from benchmark.task_registry import TaskRegistry


class HangingDependency(httpx.AsyncBaseTransport):
    """Task-agnostic dependency used to observe finite timeout behavior."""

    def __init__(self, adapter, settings):
        self.adapter = adapter
        self.settings = settings
        self.attempts = []
        self.contract_violations = []
        self.virtual_time_s = 0.0

    async def handle_async_request(self, request):
        body = await request.aread()
        violation = self.adapter.inspect_dependency_request(
            request, body, "timeout_guard"
        )
        if violation:
            self.contract_violations.append(violation)
            self.attempts.append(
                {"method": request.method, "path": request.url.path,
                 "timeout_mode": "contract_violation", "bounded": False}
            )
            return httpx.Response(400, request=request)
        policy = self.adapter.timeout_guard
        limit = (
            self.settings.timeout_s + policy.tolerance_s
            if policy.timeout_limit == "per_attempt"
            else self.settings.deadline_s
        )
        config = request.extensions.get("timeout")
        values = list(config.values()) if isinstance(config, dict) and config else []
        finite = bool(values) and all(
            type(value) in {int, float} and math.isfinite(value) and value > 0
            for value in values
        )
        if finite and max(values) <= limit:
            observed = float(max(values))
            self.virtual_time_s += observed
            self.attempts.append(
                {"method": request.method, "path": request.url.path,
                 "timeout_mode": "httpx_configuration",
                 "observed_timeout_s": observed, "bounded": True}
            )
            raise httpx.ReadTimeout("scripted hanging dependency", request=request)
        started = time.perf_counter()
        try:
            await asyncio.sleep(self.settings.deadline_s * 2)
        except asyncio.CancelledError:
            observed = time.perf_counter() - started
            self.attempts.append(
                {"method": request.method, "path": request.url.path,
                 "timeout_mode": "external_cancellation",
                 "observed_timeout_s": observed,
                 "bounded": observed <= max(0.0, limit - 0.01)}
            )
            raise


async def evaluate_timeout_guard(adapter, factory, condition):
    policy = adapter.timeout_guard
    if policy is None or condition not in policy.required_conditions:
        return None
    settings = AppSettings()
    dependency = HangingDependency(adapter, settings)
    app = factory(dependency, settings)
    status = body = error = None
    started = time.perf_counter()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://artifact.test"
            ) as client:
                response = await asyncio.wait_for(
                    adapter.invoke(client, settings), settings.deadline_s
                )
            status = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = response.text
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - started
    evidence = {
        "response_status": status,
        "response_json": body,
        "unhandled_exception": error,
        "wall_latency_s": wall,
        "virtual_dependency_time_s": dependency.virtual_time_s,
        "effective_latency_s": wall + dependency.virtual_time_s,
        "attempts": dependency.attempts,
        "contract_violations": dependency.contract_violations,
        "final_state": adapter.snapshot_state(app, dependency),
    }
    bounded = (
        1 <= len(dependency.attempts) <= settings.max_attempts
        and all(attempt.get("bounded") for attempt in dependency.attempts)
    )
    passed = bool(
        error is None
        and evidence["effective_latency_s"] <= settings.deadline_s
        and bounded
        and not dependency.contract_violations
        and adapter.timeout_failure_is_safe(evidence)
    )
    return {"pass": passed, **evidence,
            "notes": [] if passed else ["finite timeout guard failed"]}


def load_factory(path: Path, module_name: str):
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.create_app


async def probe(adapter, scenario_id: str, factory) -> dict:
    settings = AppSettings()
    dependency = adapter.make_dependency(scenario_id, settings)
    app = factory(dependency, settings)
    status = body = error = None
    started = time.perf_counter()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://artifact.test"
            ) as client:
                response = await asyncio.wait_for(adapter.invoke(client, settings), settings.deadline_s)
            status = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = response.text
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - started
    snapshot = adapter.snapshot_dependency(dependency)
    virtual = float(snapshot.get("virtual_time_s", 0.0))
    evidence = {
        "scenario": scenario_id,
        "response_status": status,
        "response_json": body,
        "unhandled_exception": error,
        "wall_latency_s": wall,
        "virtual_dependency_time_s": virtual,
        "effective_latency_s": wall + virtual,
        "deadline_violated": wall + virtual > settings.deadline_s,
        "attempts": snapshot.get("attempts", []),
        "side_effects": snapshot.get("side_effects", []),
        "contract_violations": snapshot.get("contract_violations", []),
        "final_state": adapter.snapshot_state(app, dependency),
    }
    outcome, notes = adapter.classify(scenario_id, evidence)
    evidence["outcome_class"] = outcome
    evidence["notes"] = notes
    return evidence


async def evaluate(directory: str | Path, manifest: str | Path) -> dict:
    directory = Path(directory)
    metadata = json.loads((directory / "metadata.json").read_text())
    registry = TaskRegistry.from_manifest(manifest)
    adapter = registry.require(metadata["task"])
    result = {
        "artifact_id": metadata["artifact_id"],
        "task": metadata["task"],
        "condition": metadata["condition"],
        "model": metadata.get("model_provider", "external-control"),
        "task_api_version": adapter.api_version,
        "task_manifest_sha256": registry.manifest_sha256(),
        "clean_qualified": False,
        "primary_pass": False,
        "observations": [],
        "timeout_guard": None,
        "metadata": metadata,
    }
    raw_path = directory / "raw_response.json"
    if raw_path.exists():
        raw = json.loads(raw_path.read_text())
        if raw.get("stop_reason") == "max_tokens" or raw.get("status") == "incomplete":
            result["error"] = "provider_output_truncated"
            return result
    try:
        for scenario in adapter.scenarios:
            seed = evaluation_seed(metadata["artifact_id"], scenario.id)
            random.seed(seed)
            factory = load_factory(directory / "app.py", f"adapter_generated_{scenario.id}")
            row = await probe(adapter, scenario.id, factory)
            row["evaluation_seed"] = seed
            result["observations"].append(row)
            if scenario.clean:
                result["clean_qualified"] = row["outcome_class"] == "resilient_success"
                if not result["clean_qualified"]:
                    break
        if result["clean_qualified"] and adapter.timeout_guard is not None:
            seed = evaluation_seed(metadata["artifact_id"], "timeout_guard")
            random.seed(seed)
            factory = load_factory(directory / "app.py", "adapter_generated_timeout_guard")
            result["timeout_guard"] = await evaluate_timeout_guard(
                adapter, factory, metadata["condition"]
            )
            if result["timeout_guard"] is not None:
                result["timeout_guard"]["evaluation_seed"] = seed
        accepted = {
            scenario.id: scenario.accepted_outcomes for scenario in adapter.scenarios
        }
        guard_pass = result["timeout_guard"] is None or result["timeout_guard"]["pass"]
        result["primary_pass"] = bool(
            result["clean_qualified"]
            and len(result["observations"]) == len(adapter.scenarios)
            and all(row["outcome_class"] in accepted[row["scenario"]] for row in result["observations"])
            and guard_pass
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact")
    parser.add_argument("output")
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(
        json.dumps(asyncio.run(evaluate(args.artifact, args.manifest)), indent=2)
    )


if __name__ == "__main__":
    main()
