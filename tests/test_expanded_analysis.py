"""Independent numerical cases and strict main-study denominator checks."""

import importlib.util
import math
from pathlib import Path

import pytest

pytest.importorskip("numpy")
SOURCE = Path(__file__).resolve().parents[1] / "expanded_study/analysis.py"
spec = importlib.util.spec_from_file_location("expanded_analysis", SOURCE)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def test_exact_randomization_matches_direct_small_block_probabilities():
    for k0 in range(6):
        for k1 in range(6):
            total = k0+k1
            direct = 0.0
            for x in range(6):
                if 0 <= x <= total and 0 <= 5-x <= 10-total and abs(2*x-total) >= abs(k1-k0):
                    direct += math.comb(total, x)*math.comb(10-total, 5-x)/math.comb(10, 5)
            assert analysis.exact_primary([(k0, k1)]) == pytest.approx(direct)
    assert analysis.exact_primary([(0, 0)]*48) == 1
    assert 0 < analysis.exact_primary([(0, 5)]*48) < 1e-50


def test_exact_boundary_bounds_do_not_claim_zero_uncertainty():
    low, high = analysis.exact_binomial(0, 30, .05)
    assert low == 0 and high == pytest.approx(1 - .025**(1/30))
    low, high = analysis.exact_binomial(30, 30, .05)
    assert low == pytest.approx(.025**(1/30)) and high == 1


def test_holm_handles_shared_contrasts_and_nonestimable_variance():
    result = analysis.holm({"a": .01, "b": .03, "c": None})
    assert result == {"a": .03, "b": .06, "c": None}


def test_incomplete_or_validation_records_cannot_shrink_main_denominator():
    rows = analysis.synthetic_demo()
    with pytest.raises(ValueError, match="incomplete main study"):
        analysis.summarize(rows[:-1], bootstraps=10)
    rows[0]["metadata"] = {**rows[0]["metadata"], "cohort": "validation"}
    with pytest.raises(ValueError, match="frozen main cohort"):
        analysis.summarize(rows, bootstraps=10)


def test_simulated_metadata_cannot_be_mislabelled_as_actual_results():
    rows = analysis.synthetic_demo()
    for row in rows:
        row.pop("synthetic_data")
        row["metadata"] = {**row["metadata"], "simulation_only": True}
    report = analysis.summarize(rows, bootstraps=10)
    assert report["synthetic_data"] and "NOT MODEL RESULTS" in report["status"]
    rows[0]["metadata"]["simulation_only"] = False
    with pytest.raises(ValueError, match="mix synthetic and actual"):
        analysis.summarize(rows, bootstraps=10)


def test_synthetic_full_pipeline_reconciles_failures_without_becoming_research_data():
    report = analysis.summarize(analysis.synthetic_demo(), bootstraps=200)
    assert report["synthetic_data"] and "NOT MODEL RESULTS" in report["status"]
    assert report["programs"] == 4320 and len(report["cells"]) == 144
    assert len(report["primary"]) == 6 and len(report["secondary"]) == 3
    assert all(sum(row["disjoint_priority_counts"].values()) == row["failed_programs"] for row in report["failure_reconciliation"])
    assert all(row["passed_n"] <= row["reached_n"] <= row["generated_n"] == 30 for row in report["per_scenario"])
    assert all(row["shared_baseline_preserved"] for row in report["secondary"].values())


@pytest.mark.parametrize("field,value,message", [("evaluation_repeat", 2, "repeat 1"), ("reproducibility_disagreement", True, "disagreement")])
def test_primary_analysis_cannot_choose_another_repeat_or_ignore_disagreement(field, value, message):
    rows = analysis.synthetic_demo()
    rows[0][field] = value
    with pytest.raises(ValueError, match=message):
        analysis.summarize(rows, bootstraps=10)
