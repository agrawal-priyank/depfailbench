"""Parent-controlled real-time evaluator for the expanded study only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
from time import monotonic

from .contracts import Settings, TASKS, is_functional, scenarios
from .oracles import classify


def probe(task_id, scenario, *, settings=None, source=None, mutation=None):
    cfg = settings or Settings()
    if task_id not in TASKS or scenario not in scenarios(task_id):
        raise ValueError("unknown expanded task/scenario")
    if not (0 < cfg.timeout_s <= 10 and 0 < cfg.deadline_s <= 10):
        raise ValueError("invalid local evaluation time settings")
    command = [sys.executable, "-m", "benchmark.expanded.worker", "--task", task_id,
               "--scenario", scenario, "--deadline", str(cfg.deadline_s), "--timeout", str(cfg.timeout_s)]
    if source:
        command += ["--source", str(Path(source).resolve())]
    if mutation:
        command += ["--mutation", mutation]
    # Worker receives no API credentials or unrelated process environment.
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
           "PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1", "LANG": "en_US.UTF-8"}
    evidence = {"task": task_id, "scenario": scenario, "responses": [], "dependency": None,
                "application_state": {}, "watchdog_intervened": False,
                "deadline_s": cfg.deadline_s, "measurement_tolerance_s": .05,
                "timing_basis": "actual_monotonic_wall_clock"}
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stage, buffer, stderr = "startup", b"", b""
    expiry = monotonic() + 15
    done = False

    def begin_request():
        nonlocal stage, expiry
        stage = "request"
        # This is termination slack for IPC, not a relaxed pass threshold.
        # The oracle always checks the worker's measured D+0.05 elapsed time.
        expiry = monotonic() + cfg.deadline_s + .05 + .15
        process.stdin.write(b"run\n")
        process.stdin.flush()

    try:
        while not done:
            remaining = expiry - monotonic()
            if remaining <= 0:
                if stage == "startup":
                    evidence["startup_error"] = "startup watchdog expired"
                else:
                    evidence["watchdog_intervened"] = True
                break
            available = selector.select(min(remaining, .1))
            for key, _ in available:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stderr":
                    stderr = (stderr + chunk)[:65536]
                    continue
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    row = json.loads(line)
                    event = row.pop("event")
                    if event == "ready":
                        evidence.update(row)
                        begin_request()
                    elif event == "evidence":
                        evidence.update(row)
                    elif event == "public_complete":
                        more = row.pop("more_requests")
                        evidence.update(row)
                        if more:
                            begin_request()
                        else:
                            stage = "teardown"
                            expiry = monotonic() + 2
                    elif event == "result":
                        evidence.update(row)
                        done = True
                    elif event == "error":
                        evidence["startup_error" if stage == "startup" else "request_error"] = row["error"]
                        evidence["captured_output"] = row.get("captured_output", "")
                        done = True
                if done:
                    break
            if process.poll() is not None and not selector.get_map() and not done:
                evidence["startup_error" if stage == "startup" else "request_error"] = "worker exited without complete result"
                break
    except Exception as exc:
        evidence["request_error"] = f"evaluator IPC failure: {type(exc).__name__}: {exc}"
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
    if stderr:
        evidence["worker_stderr"] = stderr.decode(errors="replace")
    evidence.update(classify(task_id, scenario, cfg, evidence))
    return evidence


def evaluate(task_id, condition, *, source=None, settings=None, mutation=None, metadata=None):
    if condition not in {"C0", "C1"}:
        raise ValueError("condition must be C0 or C1")
    cfg = settings or Settings()
    result = {"task": task_id, "condition": condition, "deadline_s": cfg.deadline_s,
              "clean_qualified": False, "primary_pass": False, "observations": [],
              "metadata": metadata or {}}
    if source and Path(source).is_file():
        result["source_sha256"] = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    if (metadata or {}).get("generation_status") in {"truncated", "refused", "incomplete", "no_code"}:
        result["generation_failure"] = metadata["generation_status"]
        return result
    sequence = sorted(scenarios(task_id), key=lambda s: not is_functional(s))
    functional = [s for s in sequence if is_functional(s)]
    for scenario in sequence:
        if not is_functional(scenario) and not result["clean_qualified"]:
            break
        row = probe(task_id, scenario, settings=cfg, source=source, mutation=mutation)
        result["observations"].append(row)
        if source:
            current_hash = hashlib.sha256(Path(source).read_bytes()).hexdigest() if Path(source).is_file() else None
            if current_hash != result.get("source_sha256"):
                result["integrity_error"] = "source changed during evaluation"
                break
        if len(result["observations"]) == len(functional):
            result["clean_qualified"] = all(r["pass"] for r in result["observations"])
        if row.get("startup_error"):
            break
    result["primary_pass"] = (not result.get("integrity_error") and result["clean_qualified"] and len(result["observations"]) == len(sequence)
                              and all(r["pass"] for r in result["observations"]))
    result["scenario_total"] = len(sequence)
    result["scenario_executed"] = len(result["observations"])
    return result
