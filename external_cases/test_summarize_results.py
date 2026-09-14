import json
import tempfile
import unittest
from pathlib import Path

from summarize_results import summarize


class IndependentSummaryTests(unittest.TestCase):
    def test_recomputes_consistent_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = root / "contract.json"
            contract.write_text('{"subjects": {}}')
            import hashlib
            contract_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
            for repeat in (1, 2, 3):
                record = {
                    "contract_sha256": contract_hash,
                    "subject": "example",
                    "case": "clean",
                    "repeat": repeat,
                    "expected_class": "resilient_success",
                    "outcome_class": "resilient_success",
                    "attempt_count": 1,
                    "commit_count": 0,
                    "passed_contract": True,
                    "elapsed_s": repeat / 10,
                }
                (root / f"example__clean__r{repeat}.json").write_text(json.dumps(record))
            result = summarize(root, contract)
            self.assertEqual(result["records"], 3)
            self.assertEqual(result["cases"], 1)
            self.assertTrue(result["all_contracts_passed"])
            self.assertEqual(result["repeat_disagreements"], [])


if __name__ == "__main__":
    unittest.main()
