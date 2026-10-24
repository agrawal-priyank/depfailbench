"""Reproduce the verified historical sensitivity without a private workspace.

Only the hash-pinned local numerical helper is executed. The archived original
analysis is staged as bytes for provenance, never imported or executed. No
generated source, archived executable code, model service or network is used.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import runpy
import tempfile
import zipfile


EXPECTED_S2_SHA256 = "4a70538f1fdf7efb6ad0a7186b9a8e3c044fd0d89b74e77969590bd081bc2bfa"
EXPECTED_MATH_SHA256 = "0b7e67ffb74b385cce36a86e68f473a5d74f305d9f52ffe008678e8c155fbb2f"
EXPECTED_RESULTS_SHA256 = "b9f6588da5db45a976f06c6b29136af7b5f5b3fc7897b8bf0db6c5a417266f83"
EXPECTED_ORIGINAL_ANALYSIS_SHA256 = "3916c833bd28da13868e06c89b279e597e0adb4fa2f06b1329587b1330efee36"
ARCHIVED_ORIGINAL_ANALYSIS = (
    "DepFailBench_Array_Revision/historical/release_v1.1.0/source/src/benchmark/full_analysis.py"
)
ORIGINAL_ANALYSIS_RELATIVE = Path("work/release_v1.1.0/source/src/benchmark/full_analysis.py")
EXPECTED_NUMPY_VERSION = "2.3.5"
IGNORED_TOP_LEVEL_FIELDS = {"created_at_utc", "elapsed_seconds", "status"}
FLOAT_RELATIVE_TOLERANCE = 1e-12
FLOAT_ABSOLUTE_TOLERANCE = 1e-14


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_bytes(path: Path, expected: str, label: str) -> bytes:
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected}; got {actual}")
    return content


def compare_results(reference, reproduced, path: str = "result", numeric_counts=None) -> dict:
    """Check full structure/text and every numeric field, excluding run metadata."""
    counts = numeric_counts if numeric_counts is not None else {"integers": 0, "floats": 0, "booleans": 0}
    if isinstance(reference, dict):
        if not isinstance(reproduced, dict):
            raise AssertionError(f"Type differs at {path}")
        skip = IGNORED_TOP_LEVEL_FIELDS if path == "result" else set()
        expected_keys = set(reference) - skip
        actual_keys = set(reproduced) - skip
        if expected_keys != actual_keys:
            raise AssertionError(f"Keys differ at {path}: {expected_keys ^ actual_keys}")
        for key in sorted(expected_keys):
            compare_results(reference[key], reproduced[key], f"{path}.{key}", counts)
    elif isinstance(reference, list):
        if not isinstance(reproduced, list) or len(reference) != len(reproduced):
            raise AssertionError(f"List shape differs at {path}")
        for index, (a, b) in enumerate(zip(reference, reproduced)):
            compare_results(a, b, f"{path}[{index}]", counts)
    elif isinstance(reference, bool):
        counts["booleans"] += 1
        if type(reproduced) is not bool or reference != reproduced:
            raise AssertionError(f"Boolean differs at {path}")
    elif isinstance(reference, int):
        counts["integers"] += 1
        if type(reproduced) is not int or reference != reproduced:
            raise AssertionError(f"Integer differs at {path}: {reference} versus {reproduced}")
    elif isinstance(reference, float):
        counts["floats"] += 1
        if not isinstance(reproduced, (float, int)) or not math.isfinite(reproduced):
            raise AssertionError(f"Non-finite or nonnumeric value at {path}")
        if not math.isclose(reference, reproduced, rel_tol=FLOAT_RELATIVE_TOLERANCE,
                            abs_tol=FLOAT_ABSOLUTE_TOLERANCE):
            raise AssertionError(f"Float differs at {path}: {reference} versus {reproduced}")
    elif reference != reproduced:
        raise AssertionError(f"Value differs at {path}: {reference!r} versus {reproduced!r}")
    return counts


def reproduce(s2: Path, math_script: Path, original_results: Path, output: Path) -> dict:
    # An existing output is an error; the final exclusive-create below also
    # closes the race between this check and writing the completed reproduction.
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Output parent directory must already exist: {output.parent}")
    if not s2.is_file():
        raise FileNotFoundError(s2)
    actual_s2_sha = sha256_file(s2)
    if actual_s2_sha != EXPECTED_S2_SHA256:
        raise ValueError(f"S2 SHA-256 mismatch: expected {EXPECTED_S2_SHA256}; got {actual_s2_sha}")
    math_bytes = verified_bytes(math_script, EXPECTED_MATH_SHA256, "Numerical helper")
    reference_bytes = verified_bytes(original_results, EXPECTED_RESULTS_SHA256, "Published sensitivity results")
    reference = json.loads(reference_bytes)
    with zipfile.ZipFile(s2) as archive:
        members = [entry for entry in archive.infolist() if entry.filename == ARCHIVED_ORIGINAL_ANALYSIS]
        if len(members) != 1:
            raise ValueError("S2 must contain exactly one pinned historical analysis member")
        original_analysis_bytes = archive.read(members[0])
    archived_sha = hashlib.sha256(original_analysis_bytes).hexdigest()
    if archived_sha != EXPECTED_ORIGINAL_ANALYSIS_SHA256:
        raise ValueError("Historical analysis member SHA-256 differs from the reviewed original")

    # Do not extract the archive. Stage only two explicitly pinned files. The
    # historical file is never imported; the trusted math helper reads its hash.
    with tempfile.TemporaryDirectory(prefix="depfailbench-historical-sensitivity-") as temporary:
        staging_workspace = Path(temporary)
        staging_phase = staging_workspace / "work/historical_primary_sensitivity_2026-10-24"
        staging_phase.mkdir(parents=True)
        staged_math = staging_phase / "historical_primary_sensitivity.py"
        staged_math.write_bytes(math_bytes)
        staged_original = staging_workspace / ORIGINAL_ANALYSIS_RELATIVE
        staged_original.parent.mkdir(parents=True)
        staged_original.write_bytes(original_analysis_bytes)
        # run_name deliberately differs from __main__: the helper's file-writing
        # main() is not entered. Its simulate() only performs Bernoulli arithmetic.
        namespace = runpy.run_path(str(staged_math), run_name="verified_historical_sensitivity_math")
        numerical_numpy = namespace["np"]
        if numerical_numpy.__version__ != EXPECTED_NUMPY_VERSION:
            raise RuntimeError(f"Reproduction requires NumPy {EXPECTED_NUMPY_VERSION}; found {numerical_numpy.__version__}")
        simulate = namespace["simulate"]
        # Update the function's actual global namespace, not merely runpy's
        # returned dict. No private workspace path is read by the helper.
        simulate.__globals__["ROOT"] = staging_phase
        simulate.__globals__["WORKSPACE"] = staging_workspace
        simulate.__globals__["ORIGINAL_ANALYSIS"] = staged_original
        reproduced = simulate()
        numeric_counts = compare_results(reference, reproduced)
        if staged_original.read_bytes() != original_analysis_bytes:
            raise AssertionError("Staged historical provenance bytes changed")
        if staged_math.read_bytes() != math_bytes:
            raise AssertionError("Staged numerical helper bytes changed")

    # Recheck the local helper/results that were supplied. They remain unchanged.
    verified_bytes(math_script, EXPECTED_MATH_SHA256, "Numerical helper after reproduction")
    verified_bytes(original_results, EXPECTED_RESULTS_SHA256, "Published results after reproduction")
    reproduced["status"] = "portable reproduction passed; same retrospective illustrative sensitivity"
    reproduced["portable_reproduction"] = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "wrapper_sha256": sha256_file(Path(__file__)),
        "s2_sha256": actual_s2_sha,
        "trusted_math_script_sha256": EXPECTED_MATH_SHA256,
        "published_results_sha256": EXPECTED_RESULTS_SHA256,
        "historical_analysis_member": ARCHIVED_ORIGINAL_ANALYSIS,
        "historical_analysis_sha256": archived_sha,
        "comparison_passed": True,
        "all_grid_and_sensitivity_numbers_compared": True,
        "numeric_fields_compared": numeric_counts,
        "ignored_original_top_level_metadata": sorted(IGNORED_TOP_LEVEL_FIELDS),
        "float_relative_tolerance": FLOAT_RELATIVE_TOLERANCE,
        "float_absolute_tolerance": FLOAT_ABSOLUTE_TOLERANCE,
        "integer_rejection_counts_and_seed_require_exact_equality": True,
        "staging": "Temporary workspace; only pinned numerical helper and historical-analysis provenance bytes staged; no full archive extraction.",
        "execution": "Only the verified numerical helper ran under a non-main namespace; archived historical analysis and generated apps were never executed or imported.",
        "private_workspace_required": False,
        "network_calls": 0,
        "model_calls": 0,
        "generated_program_executions": 0,
        "historical_analysis_executions": 0,
        "original_inputs_modified": False,
    }
    with output.open("x", encoding="utf-8") as handle:
        json.dump(reproduced, handle, indent=2)
        handle.write("\n")
    return reproduced["portable_reproduction"]


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("s2_zip", type=Path, help="Unchanged Supplementary_Material_S2.zip")
    parser.add_argument("--output", type=Path, required=True, help="New JSON path; overwriting is refused")
    parser.add_argument("--math-script", type=Path, default=here / "historical_primary_sensitivity.py")
    parser.add_argument("--original-results", type=Path, default=here / "sensitivity_results.json")
    args = parser.parse_args()
    proof = reproduce(args.s2_zip, args.math_script, args.original_results, args.output)
    print(json.dumps({"output": str(args.output), "portable_reproduction": proof}, indent=2))


if __name__ == "__main__":
    main()
