"""Out-of-tree example adapter; it is not part of the four-task study."""

from __future__ import annotations

from collections import Counter

import httpx

from benchmark.task_api import ScenarioSpec, TaskAdapter, TimeoutGuardPolicy


class ExampleDependency(httpx.AsyncBaseTransport):
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.attempts = []
        self.contract_violations = []
        self.virtual_time_s = 0.0
        self.counts = Counter()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        violation = ExampleAdapter.inspect(request, body)
        self.counts["record"] += 1
        number = self.counts["record"]
        status = 200
        if self.scenario == "transient_503" and number == 1:
            status = 503
        elif self.scenario == "persistent_503":
            status = 503
        self.virtual_time_s += 0.01
        self.attempts.append(
            {"method": request.method, "path": request.url.path, "status": status}
        )
        if violation:
            self.contract_violations.append(violation)
            return httpx.Response(400, request=request)
        payload = {"id": "alpha", "value": 42} if status == 200 else {}
        return httpx.Response(status, json=payload, request=request)


class ExampleAdapter(TaskAdapter):
    task_id = "EXAMPLE_RECORD"
    display_name = "External record lookup"
    scenarios = (
        ScenarioSpec("clean", frozenset({"resilient_success"}), clean=True),
        ScenarioSpec("transient_503", frozenset({"resilient_success"})),
        ScenarioSpec("persistent_503", frozenset({"safe_failure"})),
    )
    timeout_guard = TimeoutGuardPolicy(frozenset({"C1"}))

    @staticmethod
    def inspect(request: httpx.Request, body: bytes) -> str | None:
        if request.method != "GET" or request.url.path != "/records/alpha":
            return "dependency request must be GET /records/alpha"
        return None

    def make_dependency(self, scenario_id, settings):
        return ExampleDependency(scenario_id)

    async def invoke(self, client, settings):
        return await client.get("/lookup/alpha")

    def inspect_dependency_request(self, request, body, scenario_id):
        return self.inspect(request, body)

    def snapshot_dependency(self, dependency):
        return {
            "attempts": dependency.attempts,
            "side_effects": [],
            "contract_violations": dependency.contract_violations,
            "virtual_time_s": dependency.virtual_time_s,
        }

    def classify(self, scenario_id, evidence):
        if evidence["unhandled_exception"] or evidence["deadline_violated"]:
            return "availability_failure", ["request did not terminate within its contract"]
        if evidence["contract_violations"] or len(evidence["attempts"]) > 2:
            return "unsafe_failure", ["dependency request or attempt bound violated"]
        status = evidence["response_status"]
        body = evidence["response_json"]
        if status == 200 and body == {"record": {"id": "alpha", "value": 42}}:
            expected = 2 if scenario_id == "transient_503" else 1
            if scenario_id != "persistent_503" and len(evidence["attempts"]) == expected:
                return "resilient_success", []
            return "unsafe_failure", ["success is unsupported by the required trace"]
        if status is not None and 400 <= status < 600:
            return "safe_failure", []
        return "unsafe_failure", ["invalid public result"]


TASK = ExampleAdapter()
