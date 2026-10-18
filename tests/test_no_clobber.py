import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jev_cascade as jc  # noqa: E402
import jev_client  # noqa: E402


class FailingClient(object):
    last_latency_s = 0.0

    def __init__(self, *args, **kwargs):
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        if self.calls > 2:
            raise jev_client.JevError("stub broke")
        return {"flag": {"type": "noul", "noul": 0.99}}, {}


class NoClobberTests(unittest.TestCase):
    def files(self, tmp):
        items = os.path.join(tmp, "items.jsonl")
        questions = os.path.join(tmp, "questions.json")
        policy = os.path.join(tmp, "policy.json")
        with open(items, "w", encoding="utf-8") as fh:
            for number in range(3):
                fh.write(json.dumps({"id": str(number), "text": "x"}) + "\n")
        with open(questions, "w", encoding="utf-8") as fh:
            json.dump({"flag": {"type": "noul", "instructions": "flag?"}}, fh)
        with open(policy, "w", encoding="utf-8") as fh:
            json.dump({"questions": {}}, fh)
        return items, questions, policy

    def test_failed_run_keeps_existing_output_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            items, questions, policy = self.files(tmp)
            out = os.path.join(tmp, "out.jsonl")
            before = b"previous output\n"
            with open(out, "wb") as fh:
                fh.write(before)
            with mock.patch.object(jev_client, "LiveClient", FailingClient), \
                    mock.patch.object(jev_client, "get_key", return_value="x"), \
                    mock.patch.object(jc.time, "sleep"), contextlib.redirect_stderr(io.StringIO()):
                code = jc.main(["run", items, questions, policy, "--out", out, "--force"])
            with open(out, "rb") as fh:
                after = fh.read()
        self.assertEqual(code, 2)
        self.assertEqual(after, before)

    def test_existing_output_requires_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            items, questions, policy = self.files(tmp)
            out = os.path.join(tmp, "out.jsonl")
            with open(out, "wb") as fh:
                fh.write(b"keep\n")
            stderr = io.StringIO()
            with mock.patch.object(jev_client, "get_key", return_value="x"), \
                    contextlib.redirect_stderr(stderr):
                code = jc.main(["run", items, questions, policy, "--out", out])
        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "error: {} exists; pass --force to overwrite\n".format(out))


if __name__ == "__main__":
    unittest.main()
