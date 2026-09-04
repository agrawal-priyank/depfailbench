from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from benchmark.artifacts import load_artifact
from benchmark.runner import run_probe
from benchmark.scenarios import T1_SCENARIOS, T4_SCENARIOS


async def evaluate(directory: Path) -> tuple[dict, list]:
    metadata, factory = load_artifact(directory)
    scenarios = T1_SCENARIOS if metadata.task == "T1" else T4_SCENARIOS
    clean = await run_probe(metadata.task, metadata.artifact_id, "clean", factory)
    rows = [clean]
    qualified = clean.outcome_class == "resilient_success"
    if qualified:
        for scenario in scenarios:
            if scenario != "clean":
                rows.append(await run_probe(metadata.task, metadata.artifact_id, scenario, factory))
    return {**metadata.__dict__, "clean_qualified": qualified}, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    metadata, rows = asyncio.run(evaluate(args.artifact))
    output = args.output or args.artifact / "observations.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps({**metadata, **row.to_dict()}) + "\n" for row in rows))
    print(json.dumps({"output": str(output), "clean_qualified": metadata["clean_qualified"], "probes": len(rows)}))


if __name__ == "__main__":
    main()
