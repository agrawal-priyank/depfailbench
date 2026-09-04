import json

import pytest

from benchmark.artifact_runner import evaluate


def write_artifact(tmp_path, *, task="T1", valid=True):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    metadata = {
        "artifact_id": "T1_C0_familyA_g1",
        "task": task,
        "condition": "C0",
        "model_provider": "test",
        "model_family": "familyA",
        "model_version": "v1",
        "generation_index": 1
    }
    (artifact / "metadata.json").write_text(json.dumps(metadata))
    source = (
        "from benchmark.fixtures.t1 import create_app as ref\n"
        "def create_app(transport, settings=None):\n"
        "    return ref('reference_resilient', transport, settings)\n"
    ) if valid else (
        "from fastapi import FastAPI\n"
        "def create_app(transport, settings=None):\n"
        "    return FastAPI()\n"
    )
    (artifact / "app.py").write_text(source)
    return artifact


async def test_clean_correct_artifact_advances_to_fault_probes(tmp_path):
    metadata, rows = await evaluate(write_artifact(tmp_path))
    assert metadata["clean_qualified"] is True
    assert len(rows) == 6


async def test_clean_incorrect_artifact_is_not_fault_probed(tmp_path):
    metadata, rows = await evaluate(write_artifact(tmp_path, valid=False))
    assert metadata["clean_qualified"] is False
    assert len(rows) == 1
