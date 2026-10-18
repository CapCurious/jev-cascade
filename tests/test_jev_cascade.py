import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "examples"))

import jev_cascade as jc  # noqa: E402
import jev_client  # noqa: E402
import make_fixtures  # noqa: E402

Q = make_fixtures.QUESTIONS
POLICY = {"questions": {qid: {"act": 0.85, "review": 0.60} for qid in Q}}


def noul(p):
    return {"type": "noul", "noul": p}


def choice(name, conf):
    return {"type": "choice", "choice": name, "confidence": conf, "probabilities": {name: conf}}


def score(index, conf):
    return {"type": "score", "score": index, "confidence": conf, "legend": {}, "probabilities": {}}


def answers(urgent=0.05, human=0.05, cat=("billing", 0.97), sent=(1.05, 0.95)):
    return {"urgent": noul(urgent), "needs_human": noul(human), "category": choice(*cat),
            "sentiment": score(*sent)}


class FixtureTests(unittest.TestCase):
    def test_same_seed_same_bytes(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            make_fixtures.write(a, seed=7)
            make_fixtures.write(b, seed=7)
            for name in ("tickets.jsonl", "questions.json", "policy.json"):
                with open(os.path.join(a, name), "rb") as fa, open(os.path.join(b, name), "rb") as fb:
                    self.assertEqual(fa.read(), fb.read())

    def test_shape_and_committed_file_matches(self):
        items = make_fixtures.build(7)
        self.assertEqual(len(items), 120)
        self.assertEqual(len({it["text"] for it in items}), 120)
        cats = [it["labels"]["category"] for it in items]
        self.assertEqual({c: cats.count(c) for c in set(cats)},
                         {"billing": 30, "bug": 30, "account": 30, "other": 30})
        self.assertTrue(all(1 <= it["labels"]["sentiment"] <= 5 for it in items))
        self.assertEqual(jc.load_jsonl(os.path.join(ROOT, "examples", "tickets.jsonl")), items)

    def test_other_seed_differs(self):
        self.assertNotEqual(make_fixtures.build(7), make_fixtures.build(8))

    def test_default_policy_is_unfitted(self):
        policy = jc.load_json(os.path.join(ROOT, "examples", "policy.json"))
        self.assertEqual(set(policy["questions"]), set(Q))
        for entry in policy["questions"].values():
            self.assertEqual((entry["act"], entry["review"]), (0.85, 0.60))
        self.assertIn("not fitted", policy["fitted_on"]["source"])


class BandTests(unittest.TestCase):
    def test_noul_uses_max_p_one_minus_p(self):
        view = jc.view_stage_one(answers(urgent=0.05, human=0.70), Q, POLICY)
        self.assertAlmostEqual(view["urgent"]["certainty"], 0.95)   # a confident no acts
        self.assertEqual(view["urgent"]["band"], "act")
        self.assertFalse(view["urgent"]["answer"])
        self.assertEqual(view["needs_human"]["band"], "review")     # 0.70 sits in 0.60 to 0.85
        self.assertTrue(view["needs_human"]["answer"])

    def test_noul_escalates_near_a_coin_flip(self):
        view = jc.view_stage_one(answers(urgent=0.45), Q, POLICY)
        self.assertEqual(view["urgent"]["band"], "escalate")        # certainty 0.55

    def test_choice_uses_confidence(self):
        self.assertEqual(jc.view_stage_one(answers(cat=("bug", 0.90)), Q, POLICY)["category"]["band"], "act")
        self.assertEqual(jc.view_stage_one(answers(cat=("bug", 0.70)), Q, POLICY)["category"]["band"], "review")
        view = jc.view_stage_one(answers(cat=("bug", 0.40)), Q, POLICY)
        self.assertEqual((view["category"]["band"], view["category"]["answer"]), ("escalate", "bug"))

    def test_score_is_zero_based_index_shown_one_based(self):
        view = jc.view_stage_one(answers(sent=(1.05, 0.95)), Q, POLICY)
        self.assertEqual(view["sentiment"]["answer"], 2)            # index 1.05 is "negative", level 2
        self.assertEqual(jc.view_stage_one(answers(sent=(3.6, 0.9)), Q, POLICY)["sentiment"]["answer"], 5)
        self.assertEqual(jc.view_stage_one(answers(sent=(0.0, 0.9)), Q, POLICY)["sentiment"]["answer"], 1)
        self.assertEqual(jc.view_stage_one(answers(sent=(1.0, 0.7)), Q, POLICY)["sentiment"]["band"], "review")
        self.assertEqual(jc.view_stage_one(answers(sent=(1.0, 0.5)), Q, POLICY)["sentiment"]["band"], "escalate")

    def test_any_question_below_act_escalates(self):
        self.assertFalse(jc.needs_stage_two(jc.view_stage_one(answers(), Q, POLICY)))
        self.assertTrue(jc.needs_stage_two(jc.view_stage_one(answers(sent=(1.0, 0.84)), Q, POLICY)))

    def test_per_question_policy_overrides_defaults(self):
        policy = {"questions": {"urgent": {"act": 0.99, "review": 0.9}}}
        view = jc.view_stage_one(answers(urgent=0.05), Q, policy)
        self.assertEqual(view["urgent"]["band"], "review")          # certainty 0.95 is under the 0.99 act line
        self.assertEqual(jc.bands_for(policy, "category"), (0.85, 0.60))

    def test_band_edges_are_inclusive(self):
        self.assertEqual(jev_client.band(0.85), "act")
        self.assertEqual(jev_client.band(0.60), "review")


class StageTwoParseTests(unittest.TestCase):
    GOOD = '{"urgent": true, "needs_human": false, "category": "bug", "sentiment": 2}'

    def test_clean_reply(self):
        fields, err = jc.parse_stage_two(self.GOOD, Q)
        self.assertEqual(fields, {"urgent": True, "needs_human": False, "category": "bug", "sentiment": 2})
        self.assertIsNone(err)

    def test_fenced_and_chatty_reply(self):
        text = "Sure, here you go:\n```json\n" + self.GOOD + "\n```\nHope that helps."
        fields, err = jc.parse_stage_two(text, Q)
        self.assertIsNone(err)
        self.assertEqual(fields["category"], "bug")

    def test_malformed_reply_gives_all_none(self):
        for text in ("I think this is urgent.", '{"urgent": true,', "", None, "[1, 2]"):
            fields, err = jc.parse_stage_two(text, Q)
            self.assertEqual(set(fields.values()), {None})
            self.assertIn("no JSON object", err)

    def test_invalid_fields_become_none(self):
        text = '{"urgent": "Yes", "needs_human": "maybe", "category": "Refund", "sentiment": 7}'
        fields, err = jc.parse_stage_two(text, Q)
        self.assertEqual(fields, {"urgent": True, "needs_human": None, "category": None, "sentiment": None})
        self.assertIn("needs_human", err)

    def test_score_rejects_bool_and_fractions(self):
        self.assertIsNone(jc.coerce(True, Q["sentiment"]))
        self.assertIsNone(jc.coerce(2.5, Q["sentiment"]))
        self.assertEqual(jc.coerce("4", Q["sentiment"]), 4)
        self.assertEqual(jc.coerce(3.0, Q["sentiment"]), 3)

    def test_prompt_names_every_field(self):
        prompt = jc.build_prompt("My card was declined.", Q)
        for qid in Q:
            self.assertIn(qid, prompt)
        self.assertIn("My card was declined.", prompt)
        self.assertIn("exactly one JSON object", prompt)


class ShellTests(unittest.TestCase):
    def test_prompt_goes_to_stdin_and_runs_in_a_temp_dir(self):
        template = shlex.join([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"])
        out, secs, err = jc.run_shell(template, "hello")
        self.assertEqual(out.strip(), "HELLO")
        self.assertIsNone(err)

    def test_prompt_placeholder(self):
        template = shlex.join([sys.executable, "-c", "import sys; print(sys.argv[1])"]) + " {prompt}"
        out, _, err = jc.run_shell(template, "it's quoted")
        self.assertEqual(out.strip(), "it's quoted")

    def test_timeout_and_missing_command_are_errors_not_crashes(self):
        template = shlex.join([sys.executable, "-c", "import time; time.sleep(5)"])
        _, _, err = jc.run_shell(template, "x", timeout=0.5)
        self.assertIn("timeout", err)
        _, _, err = jc.run_shell("definitely-not-a-command-xyz", "x")
        self.assertIn("could not start", err)


class StubClient(object):
    last_latency_s = 0.2

    def __init__(self, canned):
        self.canned = canned

    def ask(self, state, questions):
        return self.canned, {"input_tokens": 1000, "output_tokens": 10}


class StubStageTwo(object):
    def __init__(self, raw):
        self.raw, self.calls = raw, 0

    def reply(self, item, prompt):
        self.calls += 1
        return self.raw, 2.0, None


def ctx_for(canned, raw, limit=None):
    return {"client": StubClient(canned), "latency": None, "questions": Q, "policy": POLICY,
            "stage2": StubStageTwo(raw), "stage2_limit": limit, "stage2_done": 0, "stage2_cost": None,
            "rec1": [], "rec2": []}


ITEM = {"id": "t1", "text": "x", "labels": {"urgent": False, "needs_human": False,
                                           "category": "bug", "sentiment": 2}}
S2 = '{"urgent": true, "needs_human": true, "category": "account", "sentiment": 4}'


class RunItemTests(unittest.TestCase):
    def test_confident_item_never_reaches_stage_two(self):
        ctx = ctx_for(answers(), S2)
        row = jc.run_item(ITEM, ctx)
        self.assertEqual((row["stage"], row["escalated"], ctx["stage2"].calls), ("act", False, 0))
        self.assertEqual(row["final"]["category"], "billing")
        self.assertAlmostEqual(row["cost_usd"]["stage1"], 0.000042)

    def test_stage_two_replaces_only_the_fields_below_act(self):
        ctx = ctx_for(answers(cat=("billing", 0.5)), S2)
        row = jc.run_item(ITEM, ctx)
        self.assertEqual(row["stage"], "stage2")
        self.assertEqual(row["final"]["category"], "account")        # was unsure, stage two decides
        self.assertEqual(row["final"]["urgent"], False)              # was sure, stage one stays
        self.assertEqual(row["final_source"]["category"], "stage2")
        self.assertEqual(row["final_source"]["urgent"], "stage1")
        self.assertEqual(row["latency_s"]["stage2"], 2.0)
        self.assertEqual(row["cost_usd"]["stage2"], 0.0)
        self.assertEqual(len(ctx["rec2"]), 1)

    def test_malformed_stage_two_falls_back_to_stage_one(self):
        row = jc.run_item(ITEM, ctx_for(answers(cat=("billing", 0.5)), "no idea"))
        self.assertEqual(row["final"]["category"], "billing")
        self.assertEqual(row["final_source"]["category"], "stage1")
        self.assertIn("no JSON object", row["stage2_error"])

    def test_stage_two_limit_skips_and_keeps_stage_one(self):
        ctx = ctx_for(answers(cat=("billing", 0.5)), S2, limit=1)
        jc.run_item(ITEM, ctx)
        row = jc.run_item(ITEM, ctx)
        self.assertEqual(ctx["stage2"].calls, 1)
        self.assertIsNone(row["stage2"])
        self.assertIn("--stage2-limit", row["stage2_error"])
        self.assertTrue(row["escalated"])

    def test_missing_recorded_reply_counts_as_skipped_not_failed(self):
        ctx = ctx_for(answers(cat=("billing", 0.5)), S2)
        ctx["stage2"].reply = lambda item, prompt: None
        row = jc.run_item(ITEM, ctx)
        self.assertIsNone(row["stage2"])
        self.assertEqual(row["final"]["category"], "billing")

    def test_cost_per_call_flag(self):
        ctx = ctx_for(answers(cat=("billing", 0.5)), S2)
        ctx["stage2_cost"] = 0.01
        row = jc.run_item(ITEM, ctx)
        self.assertEqual((row["cost_usd"]["stage2"], row["cost_usd"]["stage2_note"]), (0.01, "per call"))


def mk(i, esc, s1u, s2u, s1s, s2s, labu, labs, lat2=None):
    """A hand-made output row with two fields, urgent (bool) and sentiment (int)."""
    band = "review" if esc else "act"
    row = {"id": "r{}".format(i), "escalated": esc, "stage": "stage2" if esc else "act",
           "stage1": {"urgent": {"answer": s1u, "certainty": 0.7, "band": band},
                      "sentiment": {"answer": s1s, "certainty": 0.7, "band": band}},
           "stage2": {"urgent": s2u, "sentiment": s2s} if esc else None, "stage2_error": None,
           "final": {"urgent": s2u if esc else s1u, "sentiment": s2s if esc else s1s},
           "labels": {"urgent": labu, "sentiment": labs},
           "latency_s": {"stage1": 0.2, "stage2": lat2},
           "cost_usd": {"stage1": 0.000042, "stage2": 0.0, "stage2_note": "subscription"}}
    return row


def hand_rows(s2_urgent_right=3):
    rows = [mk(i, False, True, None, 3, None, True, 3) for i in range(6)]          # six sure and right
    s1u = [True, True, False, False]            # labels all True: stage one 2 of 4
    s2u = [True] * s2_urgent_right + [False] * (4 - s2_urgent_right)
    s1s, s2s = [1, 1, 1, 2], [1, 2, 2, 2]       # labels all 2? see below
    for k in range(4):
        rows.append(mk(6 + k, True, s1u[k], s2u[k], s1s[k], s2s[k], True, 2, lat2=2.0 * (k + 1)))
    return rows


class ReportTests(unittest.TestCase):
    def text(self, rows):
        return "\n".join(jc.report_lines(rows, "hand.jsonl"))

    def test_counts_cost_and_latency(self):
        out = self.text(hand_rows())
        self.assertIn("10 items from hand.jsonl", out)
        self.assertIn("escalated: 4 of 10 (40.0%); stage two ran on 4, skipped 0", out)
        self.assertIn("$0.0420", out)                                  # 1,000 tokens at $0.042 per million, per 1,000 items
        self.assertIn("stage one 0.20 s; stage two 5.00 s (4 items); end to end 0.20 s (90th percentile 6.20 s)", out)
        self.assertIn("not metered here: subscription", out)

    def test_accuracy_math(self):
        out = self.text(hand_rows())
        urgent = [l for l in out.splitlines() if l.startswith("urgent")][0]
        self.assertIn("6/6 (100.0%)", urgent)        # stage one inside the act band
        self.assertIn("2/4 (50.0%)", urgent)         # stage one on the escalated four
        self.assertIn("3/4 (75.0%)", urgent)         # stage two on the same four
        self.assertIn("9/10 (90.0%)", urgent)        # end to end
        self.assertIn("stronger", urgent)
        sent = [l for l in out.splitlines() if l.startswith("sentiment")][0]
        self.assertIn("1/4 (25.0%)", sent)           # stage one on the escalated four
        self.assertIn("3/4 (75.0%)", sent)

    def test_no_warning_when_stage_two_is_stronger(self):
        self.assertNotIn("WARNING", self.text(hand_rows(s2_urgent_right=4)))

    def test_warning_when_stage_two_is_not_stronger(self):
        rows = hand_rows()
        for r in rows[6:]:
            r["stage2"]["urgent"], r["stage2"]["sentiment"] = False, 1          # stage two wrong on all
        out = self.text(rows)
        self.assertIn("WARNING: stage two is not stronger", out)
        self.assertIn("21 of 24 versus 23 of 24", out)

    def test_without_labels_the_report_stops_after_cost_and_latency(self):
        rows = hand_rows()
        for r in rows:
            r["labels"] = {}
        out = self.text(rows)
        self.assertIn("no labels in the output", out)
        self.assertNotIn("WARNING", out)

    def test_invalid_stage_two_field_counts_as_wrong(self):
        rows = hand_rows()
        rows[6]["stage2"]["urgent"] = None
        self.assertIn("2/4 (50.0%)", [l for l in self.text(rows).splitlines() if l.startswith("urgent")][0])


class DemoTests(unittest.TestCase):
    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = jc.main(argv)
        return code, buf.getvalue()

    def test_demo_end_to_end(self):
        code, out = self.run_main(["--demo"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(jev_client.DEMO_LABEL))
        self.assertIn("jev-cascade report: 120 items", out)
        self.assertIn("accuracy against labels", out)

    def test_demo_run_with_limit_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "o.jsonl")
            code, out = self.run_main(["--demo", "run", "--limit", "5", "--out", path])
            self.assertEqual(code, 0)
            rows = jc.load_jsonl(path)
            self.assertEqual(len(rows), 5)
            self.assertIn("ran 5 items", out)

    def test_report_on_the_committed_live_run(self):
        code, out = self.run_main(["report", os.path.join(ROOT, "examples", "run_live.jsonl")])
        self.assertEqual(code, 0)
        self.assertIn("median latency", out)


@unittest.skipUnless(os.environ.get("JEV_LIVE") == "1"
                     and (os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")),
                     "set JEV_LIVE=1 and a Jev key to run the live test")
class LiveTests(unittest.TestCase):
    def test_stage_one_live_on_five_items_with_recorded_stage_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "live.jsonl")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = jc.main(["run", "--limit", "5", "--model", "jev-1.13.0", "--out", path,
                                "--stage2-recorded", os.path.join(ROOT, "examples", "recorded_stage2.json")])
            self.assertEqual(code, 0)
            rows = jc.load_jsonl(path)
            self.assertEqual(len(rows), 5)
            for row in rows:
                for view in row["stage1"].values():
                    self.assertTrue(0.5 <= view["certainty"] <= 1.0)
                self.assertGreater(row["cost_usd"]["stage1"], 0)


if __name__ == "__main__":
    unittest.main()
