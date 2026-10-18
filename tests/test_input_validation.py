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
import jev_client  # noqa: E402


class InputValidationTests(unittest.TestCase):
    def run_report(self, path):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = jc.main(["report", path])
        return code, stderr.getvalue()

    def test_missing_file_is_one_error_line(self):
        path = os.path.join(tempfile.gettempdir(), "jev-no-such-input.jsonl")
        code, error = self.run_report(path)
        self.assertEqual(code, 2)
        self.assertEqual(len(error.splitlines()), 1)
        self.assertIn(path + ":0:", error)

    def test_non_utf8_file_is_one_error_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "wb") as fh:
                fh.write(b'\xff\n')
            code, error = self.run_report(path)
        self.assertEqual(code, 2)
        self.assertIn(path + ":1: not UTF-8", error)
        self.assertNotIn("Traceback", error)

    def test_malformed_line_names_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"stage1": {}}\nnot json\n')
            code, error = self.run_report(path)
        self.assertEqual(code, 2)
        self.assertIn(path + ":2:", error)

    def test_missing_required_field_names_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"id": "x"}\n')
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = jc.main(["--demo", "run", path])
        self.assertEqual(code, 2)
        self.assertIn("missing required field 'text'", stderr.getvalue())

    def test_boolean_label_strings_are_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "labels.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"id": "x", "text": "x",
                                     "labels": {"urgent": "FALSE", "human": "true"}}) + "\n")
            row = jev_client.read_jsonl(path, required=("id", "text"))[0]
        self.assertEqual(row["labels"], {"urgent": False, "human": True})

    def test_malformed_questions_json_is_one_error_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            questions = os.path.join(tmp, "questions.json")
            out = os.path.join(tmp, "out.jsonl")
            with open(questions, "w", encoding="utf-8") as fh:
                fh.write("{")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = jc.main(["--demo", "run", os.path.join(ROOT, "examples", "tickets.jsonl"),
                                questions, os.path.join(ROOT, "examples", "policy.json"),
                                "--out", out])
        self.assertEqual(code, 2)
        self.assertEqual(len(stderr.getvalue().splitlines()), 1)
        self.assertIn(questions + ": not valid JSON", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
