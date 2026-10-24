"""One failure taxonomy for primary and descriptive deadline reports."""

from .contracts import Settings
from .oracles import expected_status


PRIORITY = ("generation_output_failure", "startup_failure", "functional_failure",
            "hanging_guard_failure", "deadline_failure", "safe_failure_where_recovery_required",
            "unsafe_oracle_failure", "other_failure")


def failure_flags(row):
    if row["primary_pass"]:
        return set()
    flags = set()
    observations = row.get("observations", [])
    if row.get("generation_failure"):
        flags.add("generation_output_failure")
    if any(o.get("startup_error") or o.get("outcome_class") == "construction_failure" for o in observations):
        flags.add("startup_failure")
    if not row["clean_qualified"] and not flags & {"generation_output_failure", "startup_failure"}:
        flags.add("functional_failure")
    settings = Settings(deadline_s=row.get("deadline_s", 1))
    for o in observations:
        if o["pass"]:
            continue
        if o["scenario"] == "hanging_dependency":
            flags.add("hanging_guard_failure")
        if o.get("watchdog_intervened") or any("deadline" in n for n in o.get("notes", [])):
            flags.add("deadline_failure")
        if o.get("outcome_class") == "unsafe_failure":
            flags.add("unsafe_oracle_failure")
        if any(r.get("status", 0) >= 400 and expected_status(row["task"], o["scenario"], settings, i) == {200}
               for i, r in enumerate(o.get("responses", []))):
            flags.add("safe_failure_where_recovery_required")
    return flags or {"other_failure"}
