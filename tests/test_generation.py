import json

import pytest

from benchmark.generate import extract_code, validate_provider_access
from benchmark.prompts import compose_prompt


def test_extract_code_accepts_plain_and_single_fence():
    assert extract_code("x = 1") == "x = 1\n"
    assert extract_code("```python\nx = 1\n```") == "x = 1\n"


def test_generation_plan_is_balanced_and_unique():
    plan = json.loads(open("generation_plan.json").read())
    slots = plan["slots"]
    assert len(slots) == 16
    assert len({slot["artifact_id"] for slot in slots}) == 16
    cells = {}
    for slot in slots:
        key = slot["task"], slot["condition"], slot["model"]
        cells.setdefault(key, []).append(slot["generation_index"])
    assert len(cells) == 8
    assert all(sorted(indices) == [1, 2] for indices in cells.values())


def test_composed_prompt_contains_actual_scaffold():
    prompt = compose_prompt("T1", "C0")
    assert "# Starting `app.py`" in prompt
    assert "def create_app(transport: httpx.AsyncBaseTransport" in prompt
    assert "raise NotImplementedError" in prompt


def test_execution_fails_before_calls_when_keys_are_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plan = json.loads(open("generation_plan.json").read())
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY.*ANTHROPIC_API_KEY"):
        validate_provider_access(plan, plan["slots"])
