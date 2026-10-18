"""Run the demo from an export of the tracked files, the way a fresh clone would see them.

Skipped when the kit folder has no .git directory (a downloaded zip or an exported tree has no
history to export), or when git is not installed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_GIT = os.path.isdir(os.path.join(ROOT, ".git")) and shutil.which("git") is not None


@unittest.skipUnless(HAS_GIT, "no .git directory or no git: nothing to export")
class FreshTreeTests(unittest.TestCase):
    def test_demo_run_and_report_from_exported_tree(self):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "tree.tar")
            subprocess.run(["git", "archive", "--format=tar", "-o", archive, "HEAD"], cwd=ROOT, check=True, env=env)
            tree = os.path.join(tmp, "tree")
            os.mkdir(tree)
            subprocess.run(["tar", "-xf", archive, "-C", tree], check=True, env=env)
            out = os.path.join(tmp, "run.jsonl")
            run = subprocess.run(
                [sys.executable, "jev_cascade.py", "--demo", "run", "examples/tickets.jsonl",
                 "examples/questions.json", "examples/policy.json", "--out", out],
                cwd=tree, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("DEMO (recorded response)", run.stdout)
            self.assertIn("ran 120 items", run.stdout)
            report = subprocess.run(
                [sys.executable, "jev_cascade.py", "report", out],
                cwd=tree, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("jev-cascade report: 120 items", report.stdout)


if __name__ == "__main__":
    unittest.main()
