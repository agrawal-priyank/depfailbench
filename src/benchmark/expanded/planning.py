"""Offline prompt/allocation checks. This module has no model API client."""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import random
import sysconfig

from . import PROTOCOL_VERSION
from .contracts import TASKS, is_functional, scenarios


def assets_root(explicit=None):
    candidates = [Path(explicit)] if explicit else [Path(__file__).resolve().parents[3] / "expanded_study",
                 Path(sysconfig.get_path("data")) / "share/depfailbench/expanded_study"]
    for candidate in candidates:
        if (candidate / "study.json").is_file():
            return candidate
    raise FileNotFoundError("expanded study assets not found")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prompt(task_id, condition, root=None):
    root = assets_root(root)
    if task_id not in TASKS or condition not in {"C0", "C1"}:
        raise ValueError("invalid prompt coordinates")
    return (root / "prompts" / f"{task_id}_{condition}.md").read_text()


def allocation(root=None):
    root = assets_root(root)
    design = json.loads((root / "study.json").read_text())
    configs = design["configurations"]
    if (len(configs) != 9 or len({c["id"] for c in configs}) != 9 or
            sum(c["baseline"] is True for c in configs) != 6 or
            len({c["provider"] for c in configs}) != 4 or any(c["provider"] == "xAI" for c in configs)):
        raise ValueError("expected six baseline and three extra configurations across four retained providers")
    rng = random.Random(design["seed"])
    main = []
    for round_id in range(1, 7):
        blocks = [(task_id, config) for task_id in TASKS for config in configs]
        rng.shuffle(blocks)
        for task_id, config in blocks:
            slots = [(condition, replicate) for condition in ("C0", "C1") for replicate in range(1, 6)]
            rng.shuffle(slots)
            for condition, replicate in slots:
                generation = (round_id - 1) * 5 + replicate
                main.append({"sequence": len(main) + 1,
                             "artifact_id": f"expanded_{task_id}_{config['id']}_{condition}_g{generation:02d}",
                             "cohort": "main", "task": task_id, "configuration_id": config["id"],
                             "model_id": config["model_id"], "provider": config["provider"],
                             "baseline": config["baseline"], "condition": condition,
                             "round": round_id, "generation_index": generation,
                             "block_id": f"{task_id}:{config['id']}:round-{round_id}",
                             "prompt_sha256": digest(root / "prompts" / f"{task_id}_{condition}.md")})
    validation = []
    for task_id in TASKS:
        for config in configs:
            for condition in ("C0", "C1"):
                validation.append({"sequence": 0,
                                   "artifact_id": f"validation_{task_id}_{config['id']}_{condition}",
                                   "cohort": "validation", "task": task_id,
                                   "configuration_id": config["id"], "model_id": config["model_id"],
                                   "provider": config["provider"], "baseline": config["baseline"],
                                   "condition": condition, "round": 0, "generation_index": 0,
                                   "block_id": "excluded-validation",
                                   "prompt_sha256": digest(root / "prompts" / f"{task_id}_{condition}.md")})
    rng.shuffle(validation)
    for i, row in enumerate(validation, 1):
        row["sequence"] = i
    return main, validation


def check(root=None):
    root = assets_root(root)
    design = json.loads((root / "study.json").read_text())
    shared = (root / "prompts/shared_rules.md").read_text().strip()
    scaffold = (root / "scaffold.py").read_text().strip()
    resilience = (root / "prompts/resilience.md").read_text().strip()
    manifest = json.loads((root / "task_contracts.json").read_text())
    declared = {r["id"]: r for r in manifest["tasks"]}
    if set(declared) != set(TASKS):
        raise ValueError("task manifest differs from executable task set")
    hashes = {}
    for task_id in TASKS:
        expected_scenarios = [{"id": s, "phase": "functional" if is_functional(s) else "fault"}
                              for s in scenarios(task_id)]
        if declared[task_id]["scenarios"] != expected_scenarios:
            raise ValueError(f"{task_id} scenario manifest differs from implemented checks")
        common = (root / "tasks" / f"{task_id}.md").read_text().strip()
        c0 = f"{shared}\n\n{common}\n\nStarting app.py:\n```python\n{scaffold}\n```\n"
        if prompt(task_id, "C0", root) != c0:
            raise ValueError(f"{task_id} C0 differs from its declared common source")
        if prompt(task_id, "C1", root) != c0 + "\n" + resilience + "\n":
            raise ValueError(f"{task_id} C1 has an undeclared change in common information")
        for condition in ("C0", "C1"):
            hashes[f"{task_id}:{condition}"] = digest(root / "prompts" / f"{task_id}_{condition}.md")
    main, validation = allocation(root)
    counts = Counter((r["task"], r["configuration_id"], r["condition"]) for r in main)
    blocks = Counter((r["block_id"], r["condition"]) for r in main)
    if len(main) != 4320 or len(validation) != 144 or len(counts) != 144 or set(counts.values()) != {30}:
        raise ValueError("unbalanced or incomplete expanded allocation")
    if set(blocks.values()) != {5} or len(blocks) != 864:
        raise ValueError("generation block does not match the statistical randomization design")
    ids = [r["artifact_id"] for r in main + validation]
    if len(set(ids)) != len(ids):
        raise ValueError("main/validation identifiers overlap")
    baseline_outputs = sum(r["baseline"] for r in main)
    if baseline_outputs != 2880:
        raise ValueError("focused settings duplicated or displaced a primary baseline")
    return {"protocol": PROTOCOL_VERSION, "status": "local draft checked; not frozen or execution-authorized",
            "main_slots": len(main), "primary_slots": baseline_outputs,
            "extra_setting_slots": len(main) - baseline_outputs, "excluded_validation_slots": len(validation),
            "groups": len(counts), "programs_per_group": 30,
            "prompt_hashes": hashes, "model_configurations": len(design["configurations"]),
            "task_scenario_counts": {k: {"functional": sum(is_functional(s) for s in scenarios(k)),
                                          "fault": sum(not is_functional(s) for s in scenarios(k)),
                                          "total": len(scenarios(k))} for k in TASKS},
            "model_api_calls": 0}


def write_plan(output, root=None):
    root = assets_root(root)
    report = check(root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in zip(("main_schedule.csv", "validation_schedule.csv"), allocation(root)):
        with (output / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report["schedule_sha256"] = {n: digest(output / n) for n in ("main_schedule.csv", "validation_schedule.csv")}
    (output / "local_preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
