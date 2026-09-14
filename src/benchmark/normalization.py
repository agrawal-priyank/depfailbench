"""Normalization helpers shared by evaluator probes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass


def normalize_state(value) -> dict:
    """Convert common structured state objects without weakening state checks."""

    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {"__invalid_state__": type(value).__name__}
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    try:
        return dict(vars(value))
    except (TypeError, ValueError):
        return {"__invalid_state__": type(value).__name__}
