import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jev_cascade as jc  # noqa: E402


class RangeCheckTests(unittest.TestCase):
    def run_demo(self, extra, policy=None):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--demo", "run", "--out", os.path.join(tmp, "out.jsonl")] + extra
            if policy is not None:
                path = os.path.join(tmp, "policy.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(policy, fh)
                argv = ["--demo", "run", os.path.join(ROOT, "examples", "tickets.jsonl"),
                        os.path.join(ROOT, "examples", "questions.json"), path,
                        "--out", os.path.join(tmp, "out.jsonl")]
            with contextlib.redirect_stderr(stderr):
                code = jc.main(argv)
        return code, stderr.getvalue()

    def test_policy_threshold_above_one_is_rejected(self):
        code, error = self.run_demo([], {"questions": {"urgent": {"act": 7, "review": 0.6}}})
        self.assertEqual(code, 2)
        self.assertIn("0 <= review <= act <= 1", error)

    def test_policy_review_above_act_is_rejected(self):
        code, error = self.run_demo([], {"questions": {"urgent": {"act": 0.5, "review": 0.8}}})
        self.assertEqual(code, 2)
        self.assertIn("policy question 'urgent'", error)

    def test_negative_stage2_limit_is_rejected(self):
        code, error = self.run_demo(["--stage2-limit", "-1"])
        self.assertEqual(code, 2)
        self.assertIn("--stage2-limit must be 0 or more", error)

    def test_zero_limit_is_rejected(self):
        code, error = self.run_demo(["--limit", "0"])
        self.assertEqual(code, 2)
        self.assertIn("--limit must be 1 or more", error)

    def test_negative_stage2_cost_is_rejected(self):
        code, error = self.run_demo(["--stage2-cost-per-call", "-0.01"])
        self.assertEqual(code, 2)
        self.assertIn("--stage2-cost-per-call must be 0 or more", error)


if __name__ == "__main__":
    unittest.main()
