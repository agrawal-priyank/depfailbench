"""Guard selection of immutable actual outputs and no-generation evaluation."""

import importlib.util
import builtins
import stat
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("saved_validation", ROOT / "scripts/evaluate_saved_anthropic_validation.py")
WRAPPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WRAPPER)


def test_input_guards_do_not_require_the_optional_analysis_package(monkeypatch):
    original_import = builtins.__import__
    def without_numpy(name, *args, **kwargs):
        if name.split(".")[0] == "numpy":
            raise ModuleNotFoundError("optional analysis package unavailable")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_numpy)
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    assert callable(module.prepare)


@pytest.mark.parametrize("name", ["../outside.py", "/absolute.py", "dir/../../outside.py", "dir\\outside.py"])
def test_unsafe_archive_cannot_write(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "not executed")
    with pytest.raises(ValueError, match="unsafe"):
        WRAPPER.extract_checked(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()


def test_symlink_archive_cannot_write(tmp_path):
    archive = tmp_path / "bad.zip"
    entry = zipfile.ZipInfo("link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry, "/outside")
    with pytest.raises(ValueError, match="unsafe"):
        WRAPPER.extract_checked(archive, tmp_path / "extracted")


def test_unverified_archive_is_rejected_before_extracting(tmp_path):
    archive = tmp_path / "other.zip"
    archive.write_bytes(b"a different generation artifact")
    with pytest.raises(ValueError, match="archive differs"):
        WRAPPER.prepare(archive, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_evaluation_job_cannot_enter_generation_and_has_no_model_secrets():
    workflow = (ROOT / ".github/workflows/anthropic-pilot.yml").read_text()
    paid, saved = workflow.split("  saved-code-evaluation:", 1)
    assert "!inputs.confirm_paid_generation" in saved.split("runs-on:", 1)[0]
    assert "!inputs.evaluate_saved_programs" in paid
    assert "secrets." not in saved
    assert "    permissions:\n      contents: read\n      actions: read\n" in saved
    token_steps = [s for s in saved.split("      - ") if "GH_TOKEN:" in s]
    assert len(token_steps) == 1
    assert "gh api" in token_steps[0]
    assert "python" not in token_steps[0]
