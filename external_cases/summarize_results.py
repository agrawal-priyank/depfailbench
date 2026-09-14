"""Independently recompute the external-case result table from raw records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def summarize(results_dir: Path, contract_path: Path) -> dict:
    contract_hash = sha256(contract_path)
    records = []
    for path in sorted(results_dir.glob("*__r*.json")):
        record = json.loads(path.read_text())
        if record["contract_sha256"] != contract_hash:
            raise ValueError(f"contract hash mismatch in {path.name}")
        records.append(record)

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        grouped[(record["subject"], record["case"])].append(record)

    rows = []
    disagreements = []
    for (subject, case), case_records in sorted(grouped.items()):
        signatures = {
            (
                r["outcome_class"],
                r["attempt_count"],
                r["commit_count"],
                r["passed_contract"],
            )
            for r in case_records
        }
        if len(signatures) != 1:
            disagreements.append(f"{subject}/{case}")
        rows.append(
            {
                "subject": subject,
                "case": case,
                "repeats": len(case_records),
                "expected_class": case_records[0]["expected_class"],
                "observed_class": case_records[0]["outcome_class"],
                "attempts": case_records[0]["attempt_count"],
                "commits": case_records[0]["commit_count"],
                "all_passed": all(r["passed_contract"] for r in case_records),
                "elapsed_min_s": min(r["elapsed_s"] for r in case_records),
                "elapsed_max_s": max(r["elapsed_s"] for r in case_records),
            }
        )

    return {
        "schema_version": 1,
        "contract_sha256": contract_hash,
        "subjects": len({r["subject"] for r in records}),
        "cases": len(grouped),
        "records": len(records),
        "all_contracts_passed": all(r["passed_contract"] for r in records),
        "repeat_disagreements": disagreements,
        "rows": rows,
    }


def write_csv(summary: dict, path: Path) -> None:
    fields = [
        "subject", "case", "repeats", "expected_class", "observed_class",
        "attempts", "commits", "all_passed", "elapsed_min_s", "elapsed_max_s",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary["rows"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.results_dir, args.contract)
    args.json_output.write_text(json.dumps(summary, indent=2) + "\n")
    write_csv(summary, args.csv_output)
    print(json.dumps({key: summary[key] for key in summary if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
