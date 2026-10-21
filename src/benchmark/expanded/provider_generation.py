"""Shared durable generation path and strictly offline wire-level rehearsal.

This exercises the actual request, streaming, retry, recording and accounting
path with HTTPX MockTransport. OfflineGenerator never reads credentials. The
separate LiveGenerator requires reviewed permission and accounting gates.
"""

import asyncio
from contextlib import asynccontextmanager
import os
import tempfile
import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
from time import monotonic

import httpx

from .planning import allocation, assets_root, check, prompt
from .providers import TokenRates, build_request, canonical, parse_response, sha256
from .provider_streams import ResponseAssembler, SSEDecoder
from .spending import DispatchPaused
from .dispatch_lock import slot_lock


def save_bytes(path, value):
    """Durable exclusive publication; incomplete temporary files are not evidence."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".generation-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_json(path, value):
    save_bytes(path, (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())


def publish_output(target, *, slot, config, request, parsed, cost, simulation_only, generated_at, synthetic_data=None):
    metadata = {**slot, "simulation_only": simulation_only,
        "synthetic_data": simulation_only if synthetic_data is None else synthetic_data,
        "generation_status": parsed["generation_status"], "provider_response_id": parsed["provider_response_id"],
        "resolved_model_id": parsed["resolved_model_id"], "generation_settings": config["generation_settings"],
        "output_limit_semantics": config["output_limit_semantics"], "request_sha256": request["request_sha256"],
        "provider_usage": parsed["usage"], "estimated_token_cost_usd": cost,
        "source_sha256": sha256(parsed["source"]) if parsed["source"] else None,
        "finish_reason": parsed["finish_reason"], "unexpected_tool_use": parsed["unexpected_tool_use"],
        "generated_at": generated_at, "source_processing": parsed["source_processing"]}
    files = {"response.txt": parsed["text"].encode()}
    if parsed["source"]:
        files["app.py"] = parsed["source"].encode()
    # metadata.json is the completion marker, always published last.
    files["metadata.json"] = (json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    for name, content in files.items():
        path = Path(target) / name
        if path.exists():
            if path.read_bytes() != content:
                raise DispatchPaused("recovery cannot overwrite different existing artifact evidence")
        else:
            save_bytes(path, content)
    return metadata


def retry_delay(number, retry_after=None, *, now=None):
    delay = (2, 8)[number - 1]
    if retry_after is not None:
        try:
            requested = float(retry_after)
        except ValueError:
            try:
                requested = (parsedate_to_datetime(retry_after) - (now or datetime.now(timezone.utc))).total_seconds()
            except (ValueError, TypeError, OverflowError):
                requested = 0
        if not math.isfinite(requested):
            raise DispatchPaused("invalid non-finite Retry-After")
        if requested > 120:
            raise DispatchPaused("Retry-After exceeds the reviewed 120-second retry window")
        delay = max(delay, max(0, requested))
    return delay


class _Generator:
    simulation_only = True
    synthetic_data = True
    def __init__(self, *, output, ledger, transport, rates, root=None, sleep=asyncio.sleep):
        self.root = assets_root(root)
        check(self.root)
        self.design = json.loads((self.root / "study.json").read_text())
        self.configs = {c["id"]: c for c in self.design["configurations"]}
        main, validation = allocation(self.root)
        self.slots = {s["artifact_id"]: s for s in main + validation}
        self.output, self.ledger, self.transport = Path(output), ledger, transport
        self.rates, self.sleep = rates, sleep
        self.asset_manifest = {p: sha256((self.root / p).read_text()) for p in
                               ("study.json", "scaffold.py", "task_contracts.json")}
        self.lock_sha256 = sha256((self.root.parent / "requirements.lock").read_text())
        self.semaphores = {p: asyncio.Semaphore(1 if p == "xAI" else 2)
                           for p in {c["provider"] for c in self.configs.values()}}

    def authorize_slot(self, slot):
        if self.ledger.simulation_only != self.simulation_only:
            raise DispatchPaused("generator and spending ledger execution modes differ")

    @asynccontextmanager
    async def client(self):
        async with httpx.AsyncClient(transport=self.transport, trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(1800, connect=30)) as client:
            yield client

    async def generate(self, slot, *, allowance_usd):
        if slot != self.slots.get(slot.get("artifact_id")):
            raise ValueError("slot is absent from or inconsistent with the declared allocation")
        provider = slot["provider"]
        async with self.semaphores[provider]:
            with slot_lock(self.output, slot['artifact_id']):
                return await self._generate(slot, allowance_usd)

    async def _generate(self, slot, allowance_usd):
        self.authorize_slot(slot)
        if any(sha256((self.root / p).read_text()) != expected for p, expected in self.asset_manifest.items()) or \
                sha256((self.root.parent / "requirements.lock").read_text()) != self.lock_sha256:
            raise DispatchPaused("study/scaffold/task manifest/environment changed after preparation")
        config = self.configs[slot["configuration_id"]]
        exact_prompt = prompt(slot["task"], slot["condition"], self.root)
        request = build_request(config, exact_prompt)
        if request["prompt_sha256"] != slot["prompt_sha256"]:
            raise ValueError("prompt changed after allocation")
        rates = self.rates[config["model_id"]]
        if not isinstance(rates, TokenRates):
            raise ValueError("explicit reviewed rate object required")
        fingerprint = sha256(canonical({"slot": slot, "request": request, "rates": asdict(rates)}))
        target = self.output / slot["artifact_id"]
        if target.exists():
            raise DispatchPaused("saved artifact/attempt evidence already exists; inspect or recover it without overwriting")
        attempt = self.ledger.reserve(slot["artifact_id"], slot["provider"], fingerprint, allowance_usd)
        target.mkdir(parents=True)
        save_bytes(target / "prompt.txt", exact_prompt.encode())
        save_json(target / "slot.json", slot)
        save_json(target / "configuration.json", config)
        save_json(target / "provenance.json", {
            "simulation_only": self.simulation_only, "synthetic_data": self.synthetic_data,
            "study_sha256": sha256((self.root / "study.json").read_text()),
            "scaffold_sha256": sha256((self.root / "scaffold.py").read_text()),
            "task_manifest_sha256": sha256((self.root / "task_contracts.json").read_text()),
            "dependency_lock_sha256": self.lock_sha256,
            "request_sha256": request["request_sha256"], "token_rates": asdict(rates),
            "dispatch_fingerprint": fingerprint})
        while True:
            directory = target / f"attempt_{attempt['number']:02d}"
            directory.mkdir()
            save_json(directory / "request.json", request)
            started_at = datetime.now(timezone.utc).isoformat()
            started_clock = monotonic()
            save_json(directory / "started.json", {**attempt, "started_at": started_at,
                "simulation_only": self.simulation_only, "dispatch_fingerprint": fingerprint})
            self.authorize_slot(slot)
            assembler = ResponseAssembler(provider=config["provider"])
            decoder = SSEDecoder()
            status_code, retry_after, error_kind, safe_connect_failure = None, None, None, False
            raw_bytes = bytearray()
            with (directory / "wire_response.bin").open("xb") as wire, (directory / "events.jsonl").open("x") as event_log:
                try:
                    # Offline requires mock transport; live dispatch is separately authorized.
                    async with asyncio.timeout(1800):
                        async with self.client() as client:
                            async with client.stream("POST", request["url"], headers=request["headers"], json=request["body"]) as response:
                                status_code = response.status_code
                                retry_after = response.headers.get("retry-after")
                                save_json(directory / "response_headers.json", {k: v for k, v in response.headers.items()
                                    if k in {"content-type", "retry-after", "request-id", "x-request-id"}} | {"http_status": status_code})
                                is_sse = response.headers.get("content-type", "").split(";")[0] == "text/event-stream"
                                async for chunk in response.aiter_bytes():
                                    wire.write(chunk)
                                    wire.flush()
                                    os.fsync(wire.fileno())
                                    raw_bytes.extend(chunk)
                                    if status_code == 200 and is_sse:
                                        for event in decoder.feed(chunk):
                                            event_log.write(event + "\n")
                                            event_log.flush()
                                            assembler.add(event)
                                if status_code == 200:
                                    if is_sse:
                                        decoder.feed(b"", final=True)
                                    else:
                                        decoded = json.loads(raw_bytes)
                                        if not isinstance(decoded, dict):
                                            raise ValueError("provider response must be an object")
                                        assembler.raw = decoded
                                        assembler.accepted = bool(assembler.raw.get("id"))
                                        assembler.terminal = True
                                        assembler.content_received = bool(assembler.raw.get("content") or assembler.raw.get("output") or
                                                                          assembler.raw.get("steps") or assembler.raw.get("choices"))
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                    error_kind, safe_connect_failure = type(exc).__name__, not assembler.accepted and not assembler.content_received
                except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, DispatchPaused) as exc:
                    # Exception messages may include request data; preserve a safe class only.
                    error_kind = type(exc).__name__
            finished_at = datetime.now(timezone.utc).isoformat()
            save_json(directory / "wire_complete.json", {"finished_at": finished_at, "http_status": status_code,
                "error_kind": error_kind, "safe_connect_failure": safe_connect_failure,
                "wire_sha256": hashlib.sha256(bytes(raw_bytes)).hexdigest(),
                "terminal_received": assembler.terminal, "accepted": assembler.accepted})
            raw = assembler.response()
            save_json(directory / "assembled_response.json", raw)
            try:
                parsed = parse_response(config["provider"], raw,
                                        stream_complete=assembler.terminal and error_kind is None)
            except (KeyError, ValueError, TypeError, AttributeError):
                error_kind = "AdapterSchemaError"
                parsed = parse_response(config["provider"], {}, stream_complete=False)
                parsed["provider_response_id"] = raw.get("id")
                assembler.accepted = assembler.accepted or bool(raw.get("id"))
            cost = rates.estimate(parsed["usage"])
            success_http = status_code == 200
            returned_output = (raw.get("status") in {"completed", "incomplete"} or
                               raw.get("stop_reason") in {"end_turn", "refusal", "max_tokens", "stop_sequence"} or
                               bool(raw.get("choices") and raw["choices"][0].get("finish_reason")))
            consumed = success_http and (assembler.content_received or assembler.terminal and returned_output)
            # An accepted-but-disconnected request without content is visibly unfilled.
            # It requires recovery/reconciliation, never an automatic fresh generation.
            retryable = not consumed and not assembler.accepted and (
                safe_connect_failure or status_code in {429, 500, 502, 503, 504, 529})
            outcome = parsed["generation_status"] if consumed else "service_unfilled"
            save_json(directory / "attempt.json", {**attempt, "simulation_only": self.simulation_only,
                "started_at": started_at, "finished_at": finished_at, "elapsed_s": monotonic() - started_clock,
                "connect_timeout_s": 30, "overall_generation_allowance_s": 1800,
                "http_status": status_code, "error_kind": error_kind, "content_received": assembler.content_received,
                "provider_response_id": parsed["provider_response_id"], "outcome": outcome,
                "retryable": retryable, "accepted": assembler.accepted, "consumed": consumed,
                "usage": parsed["usage"], "estimated_token_cost_usd": cost,
                "billing_uncertain": cost is None})
            if consumed:
                metadata = publish_output(target, slot=slot, config=config, request=request, parsed=parsed,
                    cost=cost, simulation_only=self.simulation_only, synthetic_data=self.synthetic_data, generated_at=finished_at)
            self.ledger.finish(attempt["id"], cost_usd=cost, outcome=outcome,
                               response_id=parsed["provider_response_id"], consume=consumed)
            if consumed:
                if not parsed["usage"]["complete"]:
                    self.ledger.pause(config["provider"], "output retained but billing usage requires reconciliation")
                return metadata
            if not retryable or attempt["number"] >= 3:
                reason = "service-only slot unfilled; recover existing response or review service/billing before resuming"
                self.ledger.pause(config["provider"], reason)
                save_json(target / "slot_state.json", {"state": "paused_unfilled", "reason": reason,
                                                       "provider_response_id": parsed["provider_response_id"]})
                raise DispatchPaused(reason)
            try:
                delay = retry_delay(attempt["number"], retry_after)
                await self.sleep(delay)
                attempt = self.ledger.reserve(slot["artifact_id"], config["provider"], fingerprint, allowance_usd)
            except DispatchPaused as exc:
                self.ledger.pause(config["provider"], str(exc))
                save_json(target / "slot_state.json", {"state": "paused_unfilled", "reason": str(exc)})
                raise


class OfflineGenerator(_Generator):
    """Wire rehearsal: credentials and real network transports remain rejected."""
    def __init__(self, *, output, ledger, transport, rates, root=None, sleep=asyncio.sleep):
        if type(transport) is not httpx.MockTransport:
            raise ValueError("this draft accepts only HTTPX MockTransport; live calls disabled")
        if not ledger.simulation_only:
            raise ValueError("offline generator requires a simulation-only ledger")
        super().__init__(output=output, ledger=ledger, transport=transport, rates=rates, root=root, sleep=sleep)
