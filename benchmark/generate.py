from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.prompts import compose_prompt, prompt_sha256
from benchmark.paths import resolve_data_path


def extract_code(text: str) -> str:
    """Accept the requested plain file or one accidental Markdown code fence."""
    match = re.fullmatch(r"\s*```(?:python)?\s*\n(.*?)\n```\s*", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip() + "\n"


def post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:2000]
        raise RuntimeError(f"provider returned HTTP {exc.code}: {detail}") from exc


def openai_generate(config: dict, prompt: str) -> tuple[str, dict]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    raw = post_json(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {key}"},
        {"model": config["model_id"], "input": prompt, "reasoning": {"effort": config["reasoning_effort"]},
         "max_output_tokens": 12000, "tool_choice": "none", "store": False},
    )
    text = raw.get("output_text")
    if not text:
        parts = []
        for item in raw.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        text = "".join(parts)
    return text, raw


def anthropic_generate(config: dict, prompt: str) -> tuple[str, dict]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    raw = post_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        {"model": config["model_id"], "max_tokens": 12000, "thinking": {"type": "adaptive"},
         "output_config": {"effort": config["effort"]}, "messages": [{"role": "user", "content": prompt}]},
    )
    text = "".join(block.get("text", "") for block in raw.get("content", []) if block.get("type") == "text")
    return text, raw


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_provider_access(plan: dict, selected: list[dict]) -> None:
    providers = {plan["models"][slot["model"]]["provider"] for slot in selected}
    missing = []
    if "OpenAI" in providers and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if "Anthropic" in providers and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        raise RuntimeError("missing provider credentials: " + ", ".join(missing))


def generate_slot(plan: dict, slot: dict, artifacts_root: Path) -> Path:
    model = plan["models"][slot["model"]]
    prompt = compose_prompt(slot["task"], slot["condition"])
    target = artifacts_root / slot["artifact_id"]
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {target}")
    scaffold_path = resolve_data_path(Path("scaffolds") / slot["task"] / "app.py")
    try:
        if model["provider"] == "OpenAI":
            text, raw = openai_generate(model, prompt)
        elif model["provider"] == "Anthropic":
            text, raw = anthropic_generate(model, prompt)
        else:
            raise ValueError(f"unsupported provider {model['provider']}")
        if not text or not text.strip():
            raise RuntimeError("provider returned no source code")
        target.mkdir(parents=True)
        metadata = {
            "artifact_id": slot["artifact_id"], "task": slot["task"], "condition": slot["condition"],
            "model_provider": model["provider"], "model_family": model["family"],
            "model_version": raw.get("model", model["model_id"]), "generation_index": slot["generation_index"],
            "prompt_sha256": prompt_sha256(prompt), "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider_response_id": raw.get("id"), "temperature": None, "top_p": None,
            "provider_usage": raw.get("usage"),
            "scaffold_sha256": file_sha256(scaffold_path),
            "dependency_lock_sha256": file_sha256(resolve_data_path("requirements.lock")),
        }
        (target / "app.py").write_text(extract_code(text))
        (target / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        (target / "prompt.txt").write_text(prompt)
        (target / "raw_response.json").write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    except Exception:
        if target.exists() and not any(target.iterdir()):
            target.rmdir()
        raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=Path("generation_plan.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--slot", action="append", help="artifact ID; repeat to select multiple")
    parser.add_argument("--execute", action="store_true", help="make provider calls; otherwise print the plan")
    args = parser.parse_args()
    plan = json.loads(resolve_data_path(args.plan).read_text())
    selected = [s for s in plan["slots"] if not args.slot or s["artifact_id"] in args.slot]
    if args.slot and len(selected) != len(set(args.slot)):
        raise SystemExit("one or more requested artifact IDs are absent from the plan")
    if not args.execute:
        print(json.dumps({"mode": "dry-run", "artifacts": [s["artifact_id"] for s in selected]}, indent=2))
        return
    validate_provider_access(plan, selected)
    for slot in selected:
        print(generate_slot(plan, slot, args.artifacts))


if __name__ == "__main__":
    main()
