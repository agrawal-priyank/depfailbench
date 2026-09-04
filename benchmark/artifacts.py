from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import FastAPI

from benchmark.fixtures.common import AppSettings


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: str
    task: str
    condition: str
    model_provider: str
    model_family: str
    model_version: str
    generation_index: int
    prompt_sha256: str | None = None
    generated_at: str | None = None
    provider_response_id: str | None = None
    provider_usage: dict[str, Any] | None = None
    scaffold_sha256: str | None = None
    dependency_lock_sha256: str | None = None
    temperature: float | None = None
    top_p: float | None = None


def load_artifact(directory: Path) -> tuple[ArtifactMetadata, Callable[[httpx.AsyncBaseTransport, AppSettings | None], FastAPI]]:
    metadata = ArtifactMetadata(**json.loads((directory / "metadata.json").read_text()))
    if metadata.task not in {"T1", "T4"}:
        raise ValueError(f"unsupported task in metadata: {metadata.task}")
    if metadata.condition not in {"C0", "C1"}:
        raise ValueError(f"unsupported condition in metadata: {metadata.condition}")
    if metadata.generation_index not in {1, 2}:
        raise ValueError("generation_index must be 1 or 2 for the locked pilot")
    app_path = directory / "app.py"
    spec = importlib.util.spec_from_file_location(f"generated_{metadata.artifact_id}", app_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {app_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_app", None)
    if not callable(factory):
        raise ValueError(f"{app_path} does not export callable create_app")
    return metadata, factory
