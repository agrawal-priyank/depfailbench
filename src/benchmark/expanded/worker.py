"""One isolated scenario. The parent owns the independent request watchdog."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import dataclasses
import importlib.util
import io
import json
import sys
from time import monotonic

import httpx

from .contracts import Settings, public_requests
from .dependency import Dependency
from .reference import create_reference

CONTROL = sys.stdout


class Capture(io.StringIO):
    def write(self, value):
        room = max(0, 65536 - self.tell())
        super().write(value[:room])
        return len(value)


def emit(row):
    CONTROL.write(json.dumps(row, allow_nan=False) + "\n")
    CONTROL.flush()


def normalize(value):
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    return {"unrecognized_state_type": type(value).__name__}


async def execute(args):
    settings = Settings(timeout_s=args.timeout, deadline_s=args.deadline)
    dependency = Dependency(args.task, args.scenario, settings)
    dependency.event_sink = lambda snapshot: emit({"event": "evidence", "dependency": snapshot})
    startup_started = monotonic()
    if args.source:
        spec = importlib.util.spec_from_file_location("expanded_generated", args.source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        app = module.create_app(dependency, settings)
    else:
        app = create_reference(args.task, dependency, settings, mutation=args.mutation)
    responses = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://artifact.test") as client:
            emit({"event": "ready", "startup_s": monotonic() - startup_started})
            for index, public in enumerate(public_requests(args.task, args.scenario)):
                if sys.stdin.readline().strip() != "run":
                    raise RuntimeError("missing parent request handshake")
                dependency.public_index = index
                started = monotonic()
                dependency.public_started = started
                response = await client.request(public["method"], public["path"], json=public["json"])
                elapsed = monotonic() - started
                try:
                    body = response.json()
                except ValueError:
                    body = response.text
                responses.append({"status": response.status_code, "body": body, "wall_latency_s": elapsed})
                emit({"event": "public_complete", "responses": responses,
                      "dependency": dependency.snapshot(), "more_requests": index + 1 < len(public_requests(args.task, args.scenario))})
    state = {name: normalize(getattr(app.state, name, {})) for name in ("orders", "reservations")}
    emit({"event": "result", "responses": responses, "dependency": dependency.snapshot(),
          "application_state": state})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--source")
    parser.add_argument("--mutation")
    args = parser.parse_args()
    capture = Capture()
    try:
        with redirect_stdout(capture), redirect_stderr(capture):
            asyncio.run(execute(args))
    except BaseException as exc:
        emit({"event": "error", "error": f"{type(exc).__name__}: {exc}", "captured_output": capture.getvalue()})


if __name__ == "__main__":
    main()
