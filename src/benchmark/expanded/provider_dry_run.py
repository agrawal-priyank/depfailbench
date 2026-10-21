"""Rehearse all selected validation slots with explicitly SYNTHETIC HTTP responses."""

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx

from .planning import allocation, assets_root
from .provider_generation import OfflineGenerator, save_json
from .providers import ENDPOINTS, TokenRates
from .spending import SpendingLedger


def fixture(provider, model=None, root=None):
    data = json.loads((assets_root(root) / "provider_fixtures.json").read_text())
    def replace(value):
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return data["source"] if value == "__SOURCE__" else value
    raw = replace(data["responses"][provider])
    if model:
        raw["model"] = model
    return raw


def stream_events(provider, raw):
    """Documented event families, constructed locally rather than API captures."""
    source = json.loads((assets_root() / "provider_fixtures.json").read_text())["source"]
    if provider in {"OpenAI", "xAI"}:
        return [{"type": "response.created", "response": {"id": raw["id"], "model": raw["model"], "status": "in_progress", "output": []}},
                {"type": "response.output_text.delta", "output_index": 0, "delta": source},
                {"type": "response.completed", "response": deepcopy(raw)}]
    if provider == "Anthropic":
        start = {k: deepcopy(raw[k]) for k in ("id", "model", "usage")}
        start["usage"]["output_tokens"] = 0
        return [{"type": "message_start", "message": start},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "SYNTHETIC THINKING"}},
                {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": source}},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 60}},
                {"type": "message_stop"}]
    if provider == "Google":
        return [{"event_type": "interaction.created", "interaction": {"id": raw["id"], "model": raw["model"], "status": "in_progress"}},
                {"event_type": "step.start", "index": 0, "step": {"type": "thought"}},
                {"event_type": "step.delta", "index": 0, "delta": {"type": "text", "text": "DO NOT PUT THINKING IN SOURCE"}},
                {"event_type": "step.start", "index": 1, "step": {"type": "model_output"}},
                {"event_type": "step.delta", "index": 1, "delta": {"type": "text", "text": source},
                 "metadata": {"total_usage": deepcopy(raw["usage"])}},
                {"event_type": "interaction.completed", "interaction": {"id": raw["id"], "model": raw["model"], "status": "completed"}}]
    return [{"id": raw["id"], "model": raw["model"], "choices": [{"index": 0, "delta": {"role": "assistant", "content": source}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": deepcopy(raw["usage"])}, "[DONE]"]


def sse_bytes(events):
    return b"".join(("data: " + (e if isinstance(e, str) else json.dumps(e, ensure_ascii=False)) + "\n\n").encode("utf-8") for e in events)


async def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    design = json.loads((assets_root() / "study.json").read_text())
    rates = {c["model_id"]: TokenRates("2", "10", "synthetic://not-actual-prices", "2026-10-19") for c in design["configurations"]}
    ledger = SpendingLedger(output / "simulated_spending.sqlite", limit_usd="10")
    calls = []

    def respond(request):
        body = json.loads(request.content)
        provider = next(p for p, (_, url) in ENDPOINTS.items() if str(request.url) == url)
        calls.append({"provider": provider, "model_id": body["model"]})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=sse_bytes(stream_events(provider, fixture(provider, body["model"]))), request=request)

    generator = OfflineGenerator(output=output / "synthetic_artifacts", ledger=ledger,
                                 transport=httpx.MockTransport(respond), rates=rates)
    rows = []
    for slot in allocation()[1]:
        rows.append(await generator.generate(slot, allowance_usd="0.01"))
    source = json.loads((assets_root() / "provider_fixtures.json").read_text())["source"]
    passed = all(r["generation_status"] == "completed" and r["provider_usage"]["complete"] and
                 (output / "synthetic_artifacts" / r["artifact_id"] / "app.py").read_text() == source for r in rows)
    report = {"status": "SYNTHETIC PROVIDER REHEARSAL — NOT MODEL RESULTS", "simulation_only": True,
              "synthetic_data": True, "passed": passed, "simulated_slots": len(rows),
              "simulated_wire_requests": len(calls), "live_model_api_calls": 0,
              "actual_model_generation_charges_usd": 0,
              "providers": sorted({c["provider"] for c in calls}),
              "configuration_count": len({r["configuration_id"] for r in rows}),
              "ledger": ledger.snapshot()}
    save_json(output / "summary.json", report)
    return {k: v for k, v in report.items() if k != "ledger"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    result = asyncio.run(run(parser.parse_args().output))
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
