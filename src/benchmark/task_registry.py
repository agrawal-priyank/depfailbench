"""Deterministic, manifest-backed task adapter loading."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path

from benchmark.task_api import TASK_API_VERSION, TaskAdapter, validate_adapter


@dataclass(frozen=True)
class TaskRecord:
    id: str
    adapter_target: str
    adapter: TaskAdapter
    prompts: dict[str, str]
    scaffold: str | None


class TaskRegistry:
    def __init__(self, manifest: Path, digest: str, records: dict[str, TaskRecord]):
        self.manifest = manifest
        self._digest = digest
        self._records = records

    @classmethod
    def from_manifest(cls, path: str | Path) -> "TaskRegistry":
        path = Path(path).resolve()
        raw = path.read_bytes()
        data = json.loads(raw)
        if data.get("schema_version") != 1 or data.get("task_api_version") != TASK_API_VERSION:
            raise ValueError("unsupported task manifest version")
        records: dict[str, TaskRecord] = {}
        for entry in data.get("tasks", []):
            task_id = entry.get("id")
            if not task_id or task_id in records:
                raise ValueError(f"missing or duplicate task ID: {task_id!r}")
            target = entry.get("adapter", "")
            module_name, separator, attribute = target.partition(":")
            if not separator or not module_name or not attribute:
                raise ValueError(f"invalid adapter target for {task_id}: {target!r}")
            try:
                adapter = getattr(importlib.import_module(module_name), attribute)
            except (ImportError, AttributeError) as exc:
                raise ImportError(f"cannot load adapter {target!r} for {task_id}") from exc
            if not isinstance(adapter, TaskAdapter):
                raise TypeError(f"{target!r} does not contain a TaskAdapter")
            validate_adapter(adapter)
            if adapter.task_id != task_id:
                raise ValueError(f"manifest ID {task_id!r} does not match adapter {adapter.task_id!r}")
            records[task_id] = TaskRecord(
                id=task_id,
                adapter_target=target,
                adapter=adapter,
                prompts=dict(entry.get("prompts", {})),
                scaffold=entry.get("scaffold"),
            )
        if not records:
            raise ValueError("task manifest is empty")
        return cls(path, hashlib.sha256(raw).hexdigest(), records)

    def require(self, task_id: str) -> TaskAdapter:
        try:
            return self._records[task_id].adapter
        except KeyError as exc:
            raise KeyError(f"task {task_id!r} is not registered") from exc

    def record(self, task_id: str) -> TaskRecord:
        self.require(task_id)
        return self._records[task_id]

    def ids(self) -> tuple[str, ...]:
        return tuple(self._records)

    def manifest_sha256(self) -> str:
        return self._digest
