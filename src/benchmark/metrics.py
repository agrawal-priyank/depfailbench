from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from benchmark.types import Observation, OutcomeClass


SAFE_FAILURE_ACCEPTED = {
    ("T1", "persistent_503"),
    ("T1", "timeout"),
    ("T1", "rate_limit"),
    ("T1", "malformed_200"),
    ("T4", "persistent_503"),
    ("T4", "rate_limit"),
    ("T4", "malformed_200"),
}


def meets_probe_oracle(row: Observation) -> bool:
    if (row.task, row.scenario) in SAFE_FAILURE_ACCEPTED:
        return row.outcome_class in {OutcomeClass.RESILIENT_SUCCESS, OutcomeClass.SAFE_FAILURE}
    return row.outcome_class == OutcomeClass.RESILIENT_SUCCESS


def summarize(rows: Iterable[Observation]) -> dict:
    rows = list(rows)
    by_fixture: dict[str, list[Observation]] = defaultdict(list)
    for row in rows:
        by_fixture[row.fixture].append(row)
    summary = {}
    for fixture, group in sorted(by_fixture.items()):
        implementations = {(r.task, r.fixture) for r in group}
        clean = [r for r in group if r.scenario == "clean"]
        probes = [r for r in group if r.scenario != "clean"]
        resilient = [r for r in probes if r.outcome_class == OutcomeClass.RESILIENT_SUCCESS]
        tasks = {r.task for r in group}
        apr_passes = 0
        for task in tasks:
            applicable = [r for r in probes if r.task == task]
            if applicable and all(meets_probe_oracle(r) for r in applicable):
                apr_passes += 1
        summary[fixture] = {
            "CCR": sum(r.outcome_class == OutcomeClass.RESILIENT_SUCCESS for r in clean) / len(clean),
            "SRR": len(resilient) / len(probes),
            "APR": apr_passes / len(implementations),
            "mean_retry_amplification_factor": sum(r.retry_amplification_factor for r in group) / len(group),
            "duplicate_side_effects": sum(r.duplicate_side_effects for r in group),
            "state_consistency_failures": sum(
                r.task == "T4" and r.outcome_class == OutcomeClass.UNSAFE_FAILURE for r in group
            ),
        }
    return summary
