#!/usr/bin/env python3
"""Run the frozen external-software contract panel entirely on loopback."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.server
import importlib.metadata
import json
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any


STRIPE_ID = "pi_depfailbench_external"
SEAM_DEVICE_ID = "device_depfailbench_external"


def canonical_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _error_payload(message: str = "scripted external-case failure") -> dict:
    return {"error": {"message": message, "type": "api_error"}}


class ScenarioServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, actions: list[str], subject: str):
        super().__init__(("127.0.0.1", 0), ScenarioHandler)
        self.actions = list(actions)
        self.subject = subject
        self.attempts: list[dict[str, Any]] = []
        self.commits: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"


class ScenarioHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def scenario(self) -> ScenarioServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, *_args) -> None:
        return

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        key = self.headers.get("Idempotency-Key")
        now = time.monotonic()
        with self.scenario.lock:
            attempt_no = len(self.scenario.attempts) + 1
            action = self.scenario.actions[
                min(attempt_no - 1, len(self.scenario.actions) - 1)
            ]
            record = {
                "attempt": attempt_no,
                "started_s": now,
                "method": self.command,
                "path": self.path,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "idempotency_key_sha256": hashlib.sha256(key.encode()).hexdigest()
                if key
                else None,
                "action": action,
            }
            self.scenario.attempts.append(record)

            # Model Stripe's published idempotency semantics: a repeated key
            # returns the first committed result rather than creating a second.
            if self.scenario.subject == "stripe" and key in self.scenario.commits:
                record["action"] = "idempotent_replay"
                self._json(200, self.scenario.commits[key])
                record["completed_s"] = time.monotonic()
                return

        if action == "disconnect":
            self._disconnect()
        elif action == "commit_disconnect":
            payload = self._stripe_success()
            with self.scenario.lock:
                self.scenario.commits[key or "<missing>"] = payload
            self._disconnect()
        elif action == "timeout":
            time.sleep(0.20)
            self._json(503, _error_payload("scripted response exceeded timeout"))
        elif action == "success_commit":
            payload = self._stripe_success()
            with self.scenario.lock:
                self.scenario.commits[key or "<missing>"] = payload
            self._json(200, payload)
        elif action == "success":
            self._json(200, self._seam_success())
        elif action == "400_retry_true":
            self._json(400, _error_payload(), {"Stripe-Should-Retry": "true"})
        elif action == "503_retry_false":
            self._json(503, _error_payload(), {"Stripe-Should-Retry": "false"})
        elif action == "429_retry_after":
            self._json(429, _error_payload(), {"Retry-After": "1"})
        elif action in {"400", "409", "503"}:
            self._json(int(action), _error_payload())
        else:
            self._json(500, _error_payload(f"unknown action: {action}"))
        record["completed_s"] = time.monotonic()

    def _disconnect(self) -> None:
        self.close_connection = True
        with suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            self.connection.close()

    def _json(
        self, status: int, payload: dict, headers: dict[str, str] | None = None
    ) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        with suppress(BrokenPipeError, ConnectionResetError, OSError):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(encoded)

    @staticmethod
    def _stripe_success() -> dict:
        return {
            "id": STRIPE_ID,
            "object": "payment_intent",
            "amount": 1000,
            "currency": "usd",
            "status": "succeeded",
            "livemode": False,
        }

    @staticmethod
    def _seam_success() -> dict:
        return {
            "devices": [
                {
                    "device_id": SEAM_DEVICE_ID,
                    "connected_account_id": "ca_depfailbench",
                    "workspace_id": "workspace_depfailbench",
                    "created_at": "2026-09-14T00:00:00Z",
                    "display_name": "DepFailBench device",
                    "device_type": "august_lock",
                    "is_managed": True,
                    "capabilities_supported": ["lock"],
                    "custom_metadata": {},
                    "space_ids": [],
                    "errors": [],
                    "warnings": [],
                }
            ],
            "pagination": {"has_next_page": False, "next_page_cursor": None},
        }


def qualified_exception(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    return f"{type(exc).__module__}.{type(exc).__name__}: {exc}"


def stable(values: list[str | None]) -> bool:
    return bool(values) and None not in values and len(set(values)) == 1


def classify_stripe(
    case: dict, attempts: list[dict], commits: dict, response_id: str | None,
    exc: BaseException | None, elapsed: float,
) -> tuple[str, list[str]]:
    failures: list[str] = []
    expected = int(case["expected_attempts"])
    if len(attempts) != expected:
        failures.append(f"attempt_count={len(attempts)} expected={expected}")
    if any(a["method"] != "POST" or not a["path"].startswith("/v1/payment_intents") for a in attempts):
        failures.append("unexpected method or path")
    keys = [a["idempotency_key_sha256"] for a in attempts]
    bodies = [a["body_sha256"] for a in attempts]
    if not stable(keys):
        failures.append("missing or changing idempotency key")
    if not stable(bodies):
        failures.append("request body changed across attempts")
    if elapsed > 10:
        failures.append("case deadline exceeded")

    expected_class = case["expected_class"]
    if expected_class == "resilient_success":
        if exc is not None:
            failures.append("unexpected exception")
        if response_id != STRIPE_ID:
            failures.append("returned payment identity does not match contract")
        if len(commits) != 1:
            failures.append(f"commit_count={len(commits)} expected=1")
        elif next(iter(commits.values())).get("id") != response_id:
            failures.append("returned payment identity does not match committed identity")
    else:
        if exc is None:
            failures.append("expected typed failure was not raised")
        if commits:
            failures.append("failure path committed a payment")
    return (expected_class if not failures else "unsafe_failure", failures)


def classify_seam(
    case: dict, attempts: list[dict], response_id: str | None,
    exc: BaseException | None, elapsed: float,
) -> tuple[str, list[str]]:
    failures: list[str] = []
    expected = int(case["expected_attempts"])
    if len(attempts) != expected:
        failures.append(f"attempt_count={len(attempts)} expected={expected}")
    expected_method = case["method"]
    if any(a["method"] != expected_method for a in attempts):
        failures.append("unexpected HTTP method")
    if expected_method == "GET" and any(not a["path"].startswith("/devices/list") for a in attempts):
        failures.append("unexpected list path")
    if expected_method == "POST" and any(a["path"] != "/devices/simulate/connect" for a in attempts):
        failures.append("unexpected POST control path")
    if elapsed > 6:
        failures.append("case deadline exceeded")

    expected_class = case["expected_class"]
    if expected_class == "resilient_success":
        if exc is not None:
            failures.append("unexpected exception")
        if response_id != SEAM_DEVICE_ID:
            failures.append("returned device identity does not match contract")
    else:
        if exc is None:
            failures.append("expected typed failure was not raised")
    return (expected_class if not failures else "availability_failure", failures)


async def run_stripe(case: dict, endpoint: str) -> tuple[str | None, BaseException | None]:
    from stripe import StripeClient
    from stripe._http_client import HTTPXClient

    response_id = None
    error = None
    client = StripeClient(
        "sk_test_depfailbench_offline",
        base_addresses={"api": endpoint},
        max_network_retries=2,
        http_client=HTTPXClient(timeout=0.05),
    )
    try:
        result = await client.v1.payment_intents.create_async(
            params={"amount": 1000, "currency": "usd"}
        )
        response_id = result.id
    except BaseException as exc:  # Preserve third-party exception type in the record.
        error = exc
    finally:
        with suppress(Exception):
            await client.close_async()
    return response_id, error


def run_seam(case: dict, endpoint: str) -> tuple[str | None, BaseException | None]:
    from seam import Seam

    response_id = None
    error = None
    client = Seam.from_api_key(
        "seam_apikey_depfailbench_offline",
        endpoint=endpoint,
        timeout=0.05,
        wait_for_action_attempt=False,
    )
    try:
        if case["method"] == "GET":
            result = client.devices.list()
            response_id = result[0].device_id if result else None
        else:
            client.devices.simulate.connect(device_id=SEAM_DEVICE_ID)
    except BaseException as exc:
        error = exc
    finally:
        with suppress(Exception):
            client.client.close()
    return response_id, error


def run_single(contract_path: Path, subject: str, case_id: str, repeat: int) -> dict:
    contract_hash = canonical_hash(contract_path)
    contract = json.loads(contract_path.read_text())
    subject_spec = contract["subjects"][subject]
    case = next(item for item in subject_spec["cases"] if item["id"] == case_id)
    server = ScenarioServer(case["actions"], subject)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        if subject == "stripe":
            response_id, error = asyncio.run(run_stripe(case, server.endpoint))
        else:
            response_id, error = run_seam(case, server.endpoint)
    finally:
        elapsed = time.monotonic() - started
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    attempts = list(server.attempts)
    commits = dict(server.commits)
    if subject == "stripe":
        outcome, failures = classify_stripe(
            case, attempts, commits, response_id, error, elapsed
        )
    else:
        outcome, failures = classify_seam(case, attempts, response_id, error, elapsed)
    intervals = [
        attempts[index]["started_s"] - attempts[index - 1]["started_s"]
        for index in range(1, len(attempts))
    ]
    for attempt in attempts:
        attempt["started_s"] -= started
        if "completed_s" in attempt:
            attempt["completed_s"] -= started
    return {
        "schema_version": 1,
        "contract_sha256": contract_hash,
        "subject": subject,
        "package": subject_spec["package"],
        "package_version": importlib.metadata.version(subject_spec["package"]),
        "case": case_id,
        "repeat": repeat,
        "expected_class": case["expected_class"],
        "outcome_class": outcome,
        "passed_contract": not failures and outcome == case["expected_class"],
        "failures": failures,
        "response_id": response_id,
        "exception": qualified_exception(error),
        "elapsed_s": elapsed,
        "attempt_count": len(attempts),
        "expected_attempts": case["expected_attempts"],
        "retry_intervals_s": intervals,
        "attempts": attempts,
        "commit_count": len(commits),
        "committed_ids": sorted(
            value.get("id") for value in commits.values() if value.get("id")
        ),
    }


def semantic_signature(record: dict) -> tuple:
    return (
        record["outcome_class"],
        record["passed_contract"],
        record["attempt_count"],
        tuple((a["method"], a["path"], a["action"]) for a in record["attempts"]),
        len({a["idempotency_key_sha256"] for a in record["attempts"]}),
        len({a["body_sha256"] for a in record["attempts"]}),
        record["commit_count"],
        tuple(record["committed_ids"]),
        record["response_id"],
        record["exception"].split(":", 1)[0] if record["exception"] else None,
        tuple(record["failures"]),
    )


def run_all(contract_path: Path, output_dir: Path) -> dict:
    expected_hash = (contract_path.with_suffix(".sha256").read_text().split()[0])
    actual_hash = canonical_hash(contract_path)
    if actual_hash != expected_hash:
        raise ValueError("contract hash does not match the frozen .sha256 record")
    contract = json.loads(contract_path.read_text())
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for subject, spec in contract["subjects"].items():
        for case in spec["cases"]:
            for repeat in (1, 2, 3):
                output = output_dir / f"{subject}__{case['id']}__r{repeat}.json"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--contract",
                        str(contract_path),
                        "--subject",
                        subject,
                        "--case",
                        case["id"],
                        "--repeat",
                        str(repeat),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if completed.returncode:
                    raise RuntimeError(
                        f"{subject}/{case['id']}/r{repeat} failed: {completed.stderr}"
                    )
                records.append(json.loads(output.read_text()))

    disagreements = []
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        groups.setdefault((record["subject"], record["case"]), []).append(record)
    for key, group in groups.items():
        if len({semantic_signature(record) for record in group}) != 1:
            disagreements.append(list(key))
    summary = {
        "schema_version": 1,
        "contract_sha256": actual_hash,
        "subjects": len(contract["subjects"]),
        "cases": len(groups),
        "records": len(records),
        "all_contracts_passed": all(record["passed_contract"] for record in records),
        "repeat_disagreements": disagreements,
        "case_results": [
            {
                "subject": key[0],
                "case": key[1],
                "expected_class": group[0]["expected_class"],
                "outcome_class": group[0]["outcome_class"],
                "attempts": group[0]["attempt_count"],
                "commit_count": group[0]["commit_count"],
                "passed_all_repeats": all(record["passed_contract"] for record in group),
                "elapsed_range_s": [
                    min(record["elapsed_s"] for record in group),
                    max(record["elapsed_s"] for record in group),
                ],
            }
            for key, group in sorted(groups.items())
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--subject", choices=("stripe", "seam"))
    parser.add_argument("--case")
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--all-output", type=Path)
    args = parser.parse_args()
    if args.all_output:
        print(json.dumps(run_all(args.contract, args.all_output), indent=2))
        return
    if not all((args.subject, args.case, args.repeat, args.output)):
        parser.error("single-case mode requires --subject, --case, --repeat, and --output")
    record = run_single(args.contract, args.subject, args.case, args.repeat)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
