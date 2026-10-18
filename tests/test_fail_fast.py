import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jev_cascade as jc  # noqa: E402
import jev_client  # noqa: E402


class RaisingClient(object):
    calls = 0
    error = jev_client.JevError("network down")

    def __init__(self, *args, **kwargs):
        self.last_latency_s = 0.0

    def ask(self, state, questions):
        type(self).calls += 1
        raise type(self).error


class UncertainClient(object):
    last_latency_s = 0.0

    def __init__(self, *args, **kwargs):
        pass

    def ask(self, state, questions):
        return {"urgent": {"type": "noul", "noul": 0.5},
                "needs_human": {"type": "noul", "noul": 0.5},
                "category": {"type": "choice", "choice": "other", "confidence": 0.5},
                "sentiment": {"type": "score", "score": 2, "confidence": 0.5}}, {}


class FailingStageTwo(object):
    def __init__(self):
        self.calls = 0

    def reply(self, item, prompt):
        self.calls += 1
        return "", 0.0, "stub stage two failed"


class FailFastTests(unittest.TestCase):
    def run_live(self, client):
        client.calls = 0
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(jev_client, "LiveClient", client), \
                mock.patch.object(jev_client, "get_key", return_value="x"), \
                mock.patch.object(jc.time, "sleep"), contextlib.redirect_stderr(stderr):
            code = jc.main(["run", os.path.join(ROOT, "examples", "tickets.jsonl"),
                            os.path.join(ROOT, "examples", "questions.json"),
                            os.path.join(ROOT, "examples", "policy.json"),
                            "--out", os.path.join(tmp, "out.jsonl")])
        return code, stderr.getvalue()

    def test_default_http_timeout_is_ten_seconds(self):
        self.assertEqual(jev_client.LiveClient(key="x").timeout, 10)

    def test_401_stops_after_one_call(self):
        RaisingClient.error = jev_client.JevError("bad key", status=401)
        code, error = self.run_live(RaisingClient)
        self.assertEqual((code, RaisingClient.calls), (2, 1))
        self.assertIn("bad key", error)

    def test_three_consecutive_failures_stop(self):
        RaisingClient.error = jev_client.JevError("network down")
        code, error = self.run_live(RaisingClient)
        self.assertEqual((code, RaisingClient.calls), (2, 3))
        self.assertIn("3 calls in a row failed (last: network down)", error)

    def test_three_consecutive_stage2_failures_stop(self):
        questions = {"flag": {"type": "noul", "instructions": "flag?"}}
        stage2 = FailingStageTwo()
        ctx = {"client": UncertainClient(), "latency": None, "questions": questions,
               "policy": {"questions": {}}, "stage2": stage2, "stage2_limit": None,
               "stage2_done": 0, "stage2_cost": None, "stage2_failures": 0,
               "rec1": [], "rec2": []}
        ctx["client"].ask = lambda state, defs: ({"flag": {"type": "noul", "noul": 0.5}}, {})
        for number in range(2):
            jc.run_item({"id": str(number), "text": "x"}, ctx)
        with self.assertRaisesRegex(ValueError, "stub stage two failed"):
            jc.run_item({"id": "2", "text": "x"}, ctx)
        self.assertEqual(stage2.calls, 3)

    def test_stage2_timeout_flag_is_applied(self):
        command = shlex.join([sys.executable, "-c", "import time; time.sleep(5)"])
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.jsonl")
            started = time.time()
            with mock.patch.object(jev_client, "LiveClient", UncertainClient), \
                    mock.patch.object(jev_client, "get_key", return_value="x"), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = jc.main(["run", "--limit", "1", "--out", out,
                                "--stage2", command, "--stage2-timeout", "0.1"])
            elapsed = time.time() - started
            with open(out, "r", encoding="utf-8") as fh:
                row = json.loads(fh.readline())
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 2)
        self.assertEqual(row["stage2_error"], "timeout after 0.1 s")


if __name__ == "__main__":
    unittest.main()
