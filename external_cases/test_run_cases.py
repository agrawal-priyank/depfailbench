import json
import unittest
from pathlib import Path

from run_cases import STRIPE_ID, classify_seam, classify_stripe


def stripe_attempt(number=1, key="k", body="b"):
    return {
        "attempt": number,
        "method": "POST",
        "path": "/v1/payment_intents",
        "idempotency_key_sha256": key,
        "body_sha256": body,
    }


class ClassifierMutationTests(unittest.TestCase):
    def setUp(self):
        self.success = {
            "expected_attempts": 2,
            "expected_class": "resilient_success",
        }
        self.attempts = [stripe_attempt(1), stripe_attempt(2)]
        self.commits = {"k": {"id": STRIPE_ID}}

    def classify(self, attempts=None, commits=None, response=STRIPE_ID, error=None, elapsed=1):
        return classify_stripe(
            self.success,
            self.attempts if attempts is None else attempts,
            self.commits if commits is None else commits,
            response,
            error,
            elapsed,
        )

    def test_valid_retried_payment_passes(self):
        self.assertEqual(self.classify(), ("resilient_success", []))

    def test_missing_key_is_rejected(self):
        attempts = [stripe_attempt(1, None), stripe_attempt(2, None)]
        self.assertEqual(self.classify(attempts=attempts)[0], "unsafe_failure")

    def test_changing_key_is_rejected(self):
        attempts = [stripe_attempt(1, "a"), stripe_attempt(2, "b")]
        self.assertEqual(self.classify(attempts=attempts)[0], "unsafe_failure")

    def test_changing_body_is_rejected(self):
        attempts = [stripe_attempt(1, body="a"), stripe_attempt(2, body="b")]
        self.assertEqual(self.classify(attempts=attempts)[0], "unsafe_failure")

    def test_fourth_attempt_is_rejected(self):
        attempts = [stripe_attempt(i) for i in range(1, 5)]
        self.assertEqual(self.classify(attempts=attempts)[0], "unsafe_failure")

    def test_duplicate_commit_is_rejected(self):
        commits = {"a": {"id": STRIPE_ID}, "b": {"id": "pi_duplicate"}}
        self.assertEqual(self.classify(commits=commits)[0], "unsafe_failure")

    def test_mismatched_returned_id_is_rejected(self):
        self.assertEqual(self.classify(response="pi_fabricated")[0], "unsafe_failure")

    def test_missing_commit_is_rejected(self):
        self.assertEqual(self.classify(commits={})[0], "unsafe_failure")

    def test_case_deadline_is_enforced(self):
        self.assertEqual(self.classify(elapsed=11)[0], "unsafe_failure")

    def test_safe_failure_cannot_commit(self):
        case = {"expected_attempts": 1, "expected_class": "safe_failure"}
        outcome, _ = classify_stripe(
            case,
            [stripe_attempt()],
            self.commits,
            None,
            RuntimeError("expected"),
            1,
        )
        self.assertEqual(outcome, "unsafe_failure")

    def test_seam_success_identity_is_checked(self):
        case = {"expected_attempts": 1, "expected_class": "resilient_success", "method": "GET"}
        attempts = [{"method": "GET", "path": "/devices/list"}]
        outcome, _ = classify_seam(case, attempts, "wrong", None, 1)
        self.assertEqual(outcome, "availability_failure")

    def test_frozen_contract_is_well_formed(self):
        contract = json.loads((Path(__file__).parent / "contract.json").read_text())
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(set(contract["subjects"]), {"stripe", "seam"})
        self.assertEqual(sum(len(s["cases"]) for s in contract["subjects"].values()), 18)


if __name__ == "__main__":
    unittest.main()
