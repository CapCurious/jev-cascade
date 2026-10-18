#!/usr/bin/env python3
"""jev-cascade: run Jev on every item, send only the uncertain ones to a stronger second stage.

Stage one is one Jev call per item with every question in the call. An item whose
certainty falls below the act band on any question goes to stage two, a shell
command (the claude CLI by default) that returns one JSON object with the same
fields. `report` prints cost, latency and accuracy per stage and checks whether
stage two is actually stronger than stage one on the items it received.

    python3 jev_cascade.py --demo
    python3 jev_cascade.py run examples/tickets.jsonl examples/questions.json examples/policy.json
    python3 jev_cascade.py report examples/run_live.jsonl

Standard library only, Python 3.10 or newer.
"""
import argparse
import contextlib
import io
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time

import jev_client

ROOT = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(ROOT, "examples")
DEFAULT_STAGE2 = "claude -p --model sonnet --setting-sources project"
STATE_KEY = "ticket"
DEFAULT_ACT = 0.85
DEFAULT_REVIEW = 0.60
STAGE2_TIMEOUT = 60
WARNING_TEXT = ("An independent test on shell commands found a Sonnet second stage weaker than "
                "Jev alone (21 of 24 versus 23 of 24, 2026-10). Measure before you trust stage two.")


# ---------------------------------------------------------------- files

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise jev_client.InputError("{}: file not found".format(path))
    except UnicodeDecodeError as exc:
        raise jev_client.InputError("{}: not UTF-8 text (bad byte at offset {})".format(path, exc.start))
    except ValueError as exc:
        raise jev_client.InputError("{}: not valid JSON ({})".format(path, exc))


def load_jsonl(path, required=()):
    return jev_client.read_jsonl(path, required=required)


def dump_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
        fh.write("\n")


# ---------------------------------------------------------------- stage one maths

def bands_for(policy, qid):
    """(act, review) for a question, falling back to the community defaults."""
    entry = ((policy or {}).get("questions") or {}).get(qid) or {}
    try:
        act = float(entry.get("act", DEFAULT_ACT))
        review = float(entry.get("review", DEFAULT_REVIEW))
    except (TypeError, ValueError):
        raise ValueError("policy question '{}': act and review must be numbers in [0, 1]".format(qid))
    if not (0.0 <= review <= act <= 1.0):
        raise ValueError("policy question '{}': need 0 <= review <= act <= 1, got act={} review={}".format(
            qid, act, review))
    return act, review


def score_levels(question):
    return len(question.get("criteria") or []) or 5


def predict(answer, question):
    """The value a stage-one answer stands for: bool, option name, or 1 to N.

    A score answer is a probability-weighted 0-based index into the criteria
    list, so the 1 to N display value is round(score) + 1."""
    kind = answer["type"]
    if kind == "noul":
        return float(answer["noul"]) >= 0.5
    if kind == "choice":
        return answer["choice"]
    if kind == "score":
        return min(max(int(round(float(answer["score"]))) + 1, 1), score_levels(question))
    raise ValueError("unknown answer type: {!r}".format(kind))


def view_stage_one(answers, questions, policy):
    """Per question: the predicted value, its certainty and its band."""
    out = {}
    for qid, question in questions.items():
        answer = answers[qid]
        act, review = bands_for(policy, qid)
        cert = jev_client.certainty(answer)
        out[qid] = {"answer": predict(answer, question), "certainty": round(cert, 4),
                    "band": jev_client.band(cert, act, review)}
    return out


def needs_stage_two(view):
    """An item escalates when any question is below the act band."""
    return any(v["band"] != "act" for v in view.values())


# ---------------------------------------------------------------- stage two

def build_prompt(text, questions):
    lines = ["You are triaging one customer support ticket. Answer every question about it.", "",
             "Ticket:", '"""', text, '"""', "", "Questions:"]
    for qid, q in questions.items():
        if q["type"] == "noul":
            lines.append("- {} (true or false): {}".format(qid, q["instructions"]))
        elif q["type"] == "choice":
            options = "; ".join("{} = {}".format(k, v) for k, v in q["criteria"].items())
            lines.append("- {} (exactly one of {}): {} Options: {}.".format(
                qid, ", ".join(q["criteria"]), q["instructions"], options))
        else:
            scale = "; ".join("{} = {}".format(i + 1, c) for i, c in enumerate(q["criteria"]))
            lines.append("- {} (an integer from 1 to {}): {} Scale: {}.".format(
                qid, len(q["criteria"]), q["instructions"], scale))
    lines += ["", "Reply with exactly one JSON object and nothing else, no code fence and no commentary, "
              "with these keys: " + ", ".join(questions) + "."]
    return "\n".join(lines)


def extract_json(text):
    """Find one JSON object in a reply that may carry fences or chatter."""
    if not isinstance(text, str):
        return None
    for candidate in (text.strip(), text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def coerce(value, question):
    """A stage-two field as a bool, option name or int, or None when it is not valid."""
    kind = question["type"]
    if kind == "noul":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("yes", "true", "no", "false"):
            return value.strip().lower() in ("yes", "true")
        return None
    if kind == "choice":
        if isinstance(value, str) and value.strip().lower() in question["criteria"]:
            return value.strip().lower()
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != int(number) or not 1 <= int(number) <= score_levels(question):
        return None
    return int(number)


def parse_stage_two(text, questions):
    """(fields, error). Every field is None when it is missing or invalid."""
    obj = extract_json(text)
    if obj is None:
        return {qid: None for qid in questions}, "no JSON object in the reply"
    fields = {qid: coerce(obj.get(qid), q) for qid, q in questions.items()}
    bad = [qid for qid, v in fields.items() if v is None]
    return fields, ("invalid or missing fields: " + ", ".join(bad)) if bad else None


def run_shell(template, prompt, timeout=STAGE2_TIMEOUT):
    """Run the stage-two command. Returns (stdout, seconds, error or None).

    The prompt goes to stdin, or into the command where the template has {prompt}.
    The command runs in an empty temporary directory."""
    started = time.time()
    stdin = None
    if "{prompt}" in template:
        argv = shlex.split(template.replace("{prompt}", shlex.quote(prompt)))
    else:
        argv, stdin = shlex.split(template), prompt
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                                  timeout=timeout, cwd=tmp)
        except subprocess.TimeoutExpired:
            return "", time.time() - started, "timeout after {} s".format(timeout)
        except OSError as exc:
            return "", time.time() - started, "could not start the command: {}".format(exc)
    error = None
    if proc.returncode != 0:
        error = "exit {}: {}".format(proc.returncode, proc.stderr.strip()[:200])
    return proc.stdout, time.time() - started, error


class LiveStageTwo(object):
    def __init__(self, template, timeout=STAGE2_TIMEOUT):
        self.template, self.timeout = template, timeout

    def reply(self, item, prompt):
        return run_shell(self.template, prompt, self.timeout)


class ReplayStageTwo(object):
    def __init__(self, path):
        records = load_json(path)["records"]
        self.by_id = {r["id"]: r for r in records}

    def reply(self, item, prompt):
        rec = self.by_id.get(item["id"])
        if rec is None:
            return None
        return rec["raw"], float(rec.get("latency_s", 0.0)), None


class ReplayLatency(object):
    """Stage-one latencies stored next to the recorded responses (RecordedClient reports 0)."""

    def __init__(self, path):
        records = load_json(path)["records"]
        self.by_state = {json.dumps(r["state"], sort_keys=True): float(r.get("latency_s", 0.0))
                         for r in records}

    def get(self, state):
        return self.by_state.get(json.dumps(state, sort_keys=True), 0.0)


# ---------------------------------------------------------------- run

def ask_stage_one(client, state, question_defs):
    for attempt in range(3):
        try:
            return client.ask(state, question_defs)
        except jev_client.JevError as exc:
            if exc.status in (401, 403) or isinstance(client, jev_client.RecordedClient):
                raise
            if attempt == 2:
                raise ValueError("3 calls in a row failed (last: {}); stopping".format(exc))
            time.sleep(1.0)


def run_item(item, ctx):
    """Process one item through both stages; returns the output row."""
    questions, policy = ctx["questions"], ctx["policy"]
    state = {STATE_KEY: item["text"]}
    answers, usage = ask_stage_one(ctx["client"], state, questions)
    lat1 = ctx["latency"].get(state) if ctx["latency"] else ctx["client"].last_latency_s
    view = view_stage_one(answers, questions, policy)
    ctx["rec1"].append({"questions": {q: {"type": d["type"]} for q, d in questions.items()},
                        "state": state, "answers": answers, "usage": usage, "latency_s": round(lat1, 3)})
    row = {"id": item["id"], "escalated": needs_stage_two(view), "stage": "act", "stage1": view,
           "stage2": None, "stage2_error": None, "final": {q: v["answer"] for q, v in view.items()},
           "final_source": {q: "stage1" for q in view}, "labels": item.get("labels") or {},
           "latency_s": {"stage1": round(lat1, 3), "stage2": None},
           "cost_usd": {"stage1": jev_client.cost_usd(usage), "stage2": 0.0,
                        "stage2_note": "subscription"}}
    if not row["escalated"]:
        return row
    row["stage"] = "stage2"
    limit = ctx["stage2_limit"]
    if limit is not None and ctx["stage2_done"] >= limit:
        row["stage2_error"] = "skipped by --stage2-limit"
        return row
    reply = ctx["stage2"].reply(item, build_prompt(item["text"], questions))
    if reply is None:
        row["stage2_error"] = "no recorded stage-two reply"
        return row
    ctx["stage2_done"] += 1
    raw, lat2, error = reply
    ctx["rec2"].append({"id": item["id"], "raw": raw, "latency_s": round(lat2, 3)})
    fields, parse_error = parse_stage_two(raw, questions)
    row["stage2"], row["stage2_error"] = fields, error or parse_error
    if row["stage2_error"] and not isinstance(ctx["stage2"], ReplayStageTwo):
        ctx["stage2_failures"] = ctx.get("stage2_failures", 0) + 1
        if ctx["stage2_failures"] >= 3:
            raise ValueError("3 stage-two calls in a row failed (last: {}); stopping".format(
                row["stage2_error"]))
    else:
        ctx["stage2_failures"] = 0
    row["latency_s"]["stage2"] = round(lat2, 3)
    if ctx["stage2_cost"] is not None:
        row["cost_usd"]["stage2"], row["cost_usd"]["stage2_note"] = ctx["stage2_cost"], "per call"
    for qid, v in view.items():
        if v["band"] != "act" and fields[qid] is not None:
            row["final"][qid], row["final_source"][qid] = fields[qid], "stage2"
    return row


def cmd_run(args):
    questions, policy = load_json(args.questions), load_json(args.policy)
    if not isinstance(questions, dict):
        raise jev_client.InputError("{}: questions must be a JSON object".format(args.questions))
    if not isinstance(policy, dict) or not isinstance(policy.get("questions", {}), dict):
        raise jev_client.InputError("{}: policy questions must be a JSON object".format(args.policy))
    for qid in questions:
        bands_for(policy, qid)
    boolean_labels = tuple(qid for qid, question in questions.items()
                           if isinstance(question, dict) and question.get("type") == "noul")
    items = jev_client.read_jsonl(args.items, required=("id", "text"), booleans=boolean_labels)
    if args.limit is not None:
        items = items[:args.limit]
    model = args.model or policy.get("model") or "jev-latest"
    latency = None
    if args.demo:
        stage1_path = os.path.join(EXAMPLES, "recorded_stage1.json")
        client, latency = jev_client.RecordedClient(stage1_path), ReplayLatency(stage1_path)
        stage2 = ReplayStageTwo(args.stage2_recorded or os.path.join(EXAMPLES, "recorded_stage2.json"))
        out_path = args.out or os.path.join(tempfile.mkdtemp(prefix="jev-cascade-"), "run_demo.jsonl")
    else:
        out_path = args.out or "run.jsonl"
        if os.path.exists(out_path) and not args.force:
            raise ValueError("{} exists; pass --force to overwrite".format(out_path))
        client = jev_client.LiveClient(model=model, key=jev_client.get_key())
        stage2 = (ReplayStageTwo(args.stage2_recorded) if args.stage2_recorded
                  else LiveStageTwo(args.stage2, args.stage2_timeout))
    if args.demo and os.path.exists(out_path) and not args.force:
        raise ValueError("{} exists; pass --force to overwrite".format(out_path))
    ctx = {"client": client, "latency": latency, "questions": questions, "policy": policy,
           "stage2": stage2, "stage2_limit": args.stage2_limit, "stage2_done": 0,
           "stage2_cost": args.stage2_cost_per_call, "stage2_failures": 0, "rec1": [], "rec2": []}
    rows = []
    folder = os.path.dirname(os.path.abspath(out_path))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder,
                                     prefix=os.path.basename(out_path) + ".", suffix=".part",
                                     delete=False) as fh:
        part_path = fh.name
        for i, item in enumerate(items):
            row = run_item(item, ctx)
            rows.append(row)
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            if not args.demo and (i + 1) % 10 == 0:
                print("  {}/{} items, {} escalated so far".format(
                    i + 1, len(items), sum(r["escalated"] for r in rows)), file=sys.stderr, flush=True)
    os.replace(part_path, out_path)
    stamp = time.strftime("%Y-%m-%d")
    if args.record_stage1:
        dump_json(args.record_stage1, {"model": model, "recorded_on": stamp,
                                       "note": "synthetic tickets; replayed by --demo", "records": ctx["rec1"]})
    if args.record_stage2:
        dump_json(args.record_stage2, {"recorded_on": stamp, "command": args.stage2,
                                       "note": "raw stage-two replies; replayed by --demo",
                                       "records": ctx["rec2"]})
    print("ran {} items, {} escalated{}".format(
        len(rows), sum(r["escalated"] for r in rows), "" if args.demo else ", wrote " + out_path))
    return out_path


# ---------------------------------------------------------------- report

def frac(correct, n):
    return "{}/{} ({:.1f}%)".format(correct, n, 100.0 * correct / n) if n else "n/a"


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def secs(value):
    return "n/a" if value is None else "{:.2f} s".format(value)


def tally(pairs):
    """(correct, n) for (predicted, label) pairs; a None prediction is wrong."""
    return sum(1 for p, l in pairs if p is not None and p == l), len(pairs)


def near(pairs):
    """Within-one count for integer scores."""
    return sum(1 for p, l in pairs if p is not None and abs(p - l) <= 1)


def report_lines(rows, source="output"):
    """The report as a list of lines; pure, so tests can check the math."""
    n = len(rows)
    qids = list(rows[0]["stage1"]) if rows else []
    escalated = [r for r in rows if r["escalated"]]
    ran = [r for r in escalated if r["stage2"] is not None]
    failed = [r for r in ran if r["stage2_error"]]
    skipped = [r for r in escalated if r["stage2"] is None]
    c1 = sum(r["cost_usd"]["stage1"] for r in rows)
    c2 = sum(r["cost_usd"]["stage2"] for r in rows)
    note = rows[0]["cost_usd"]["stage2_note"] if rows else ""
    per = lambda total: total / n * 1000 if n else 0.0
    totals = [(r["latency_s"]["stage1"] or 0.0) + (r["latency_s"]["stage2"] or 0.0) for r in rows]
    out = ["jev-cascade report: {} items from {}".format(n, source),
           "escalated: {} of {} ({:.1f}%); stage two ran on {}, skipped {}, replies with a parse problem {}".format(
               len(escalated), n, 100.0 * len(escalated) / n if n else 0.0, len(ran), len(skipped), len(failed)),
           "", "cost           total       per 1,000 items",
           "stage one Jev  ${:.5f}    ${:.4f}".format(c1, per(c1)),
           ("stage two      not metered            ({})".format("subscription")
            if note == "subscription" else
            "stage two      ${:.5f}    ${:.4f}   ({})".format(c2, per(c2), note)),
           "",
           "median latency: stage one {}; stage two {} ({} items); end to end {} (90th percentile {})".format(
               secs(median(r["latency_s"]["stage1"] for r in rows)),
               secs(median(r["latency_s"]["stage2"] for r in ran)), len(ran),
               secs(median(totals)), secs(sorted(totals)[int(0.9 * (len(totals) - 1))] if totals else None))]
    labelled = [r for r in rows if r.get("labels")]
    if not labelled:
        return out + ["", "no labels in the output, accuracy not computed"]
    out += ["", "accuracy against labels (synthetic fixtures; stage two counts invalid fields as wrong)",
            "{:<12} {:<20} {:<20} {:<20} {:<20} {}".format(
                "field", "s1 in act band", "s1 on escalated", "s2 on escalated", "end to end", "s2 vs s1")]
    pooled1 = pooled2 = pooled_n = 0
    below_lines = []
    for qid in qids:
        act = [(r["stage1"][qid]["answer"], r["labels"][qid]) for r in labelled
               if r["stage1"][qid]["band"] == "act"]
        e1 = [(r["stage1"][qid]["answer"], r["labels"][qid]) for r in ran if r.get("labels")]
        e2 = [(r["stage2"][qid], r["labels"][qid]) for r in ran if r.get("labels")]
        end = [(r["final"][qid], r["labels"][qid]) for r in labelled]
        (a1, n1), (a2, n2) = tally(e1), tally(e2)
        pooled1, pooled2, pooled_n = pooled1 + a1, pooled2 + a2, pooled_n + n1
        verdict = "n/a" if not n1 else ("stronger" if a2 > a1 else "tied" if a2 == a1 else "WEAKER")
        out.append("{:<12} {:<20} {:<20} {:<20} {:<20} {}".format(
            qid, frac(*tally(act)), frac(a1, n1), frac(a2, n2), frac(*tally(end)), verdict))
        low = [r for r in ran if r.get("labels") and r["stage1"][qid]["band"] != "act"]
        b1 = tally([(r["stage1"][qid]["answer"], r["labels"][qid]) for r in low])
        b2 = tally([(r["stage2"][qid], r["labels"][qid]) for r in low])
        below_lines.append("{:<12} stage one {}   stage two {}".format(qid, frac(*b1), frac(*b2)))
        if isinstance(rows[0]["stage1"][qid]["answer"], int) and not isinstance(rows[0]["stage1"][qid]["answer"], bool):
            out.append("{:<12} within one level: s1 in act band {}, end to end {}".format(
                "", frac(near(act), len(act)), frac(near(end), len(end))))
    out += ["", "only the fields stage one was unsure about (below the act band)"] + below_lines
    if pooled_n:
        out.append("")
        out.append("escalated items, all fields pooled: stage one {}, stage two {}".format(
            frac(pooled1, pooled_n), frac(pooled2, pooled_n)))
        if pooled2 <= pooled1:
            out.append("WARNING: stage two is not stronger than stage one on the items it received. " + WARNING_TEXT)
    return out


def cmd_report(args):
    path = args.path or os.path.join(EXAMPLES, "run_live.jsonl")
    rows = load_jsonl(path, required=("stage1",))
    if not rows:
        print("error: {} has no rows".format(path), file=sys.stderr)
        return 1
    print("\n".join(report_lines(rows, os.path.basename(path))))
    return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="jev-cascade", description=__doc__.split("\n\n")[0])
    p.add_argument("--demo", action="store_true", help="replay recorded responses, no key, no network")
    p.add_argument("--model", help="Jev model id (default: the policy's model, else jev-latest)")
    shared = argparse.ArgumentParser(add_help=False)  # same flags after the subcommand
    shared.add_argument("--demo", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    shared.add_argument("--model", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", parents=[shared], help="stage one on every item, stage two on the uncertain ones")
    r.add_argument("items", nargs="?", default=os.path.join(EXAMPLES, "tickets.jsonl"))
    r.add_argument("questions", nargs="?", default=os.path.join(EXAMPLES, "questions.json"))
    r.add_argument("policy", nargs="?", default=os.path.join(EXAMPLES, "policy.json"))
    r.add_argument("--out", help="output JSONL (default run.jsonl in the current folder)")
    r.add_argument("--force", action="store_true", help="overwrite an existing --out file")
    r.add_argument("--stage2", default=DEFAULT_STAGE2, help="stage-two command; the prompt goes to stdin "
                   "or replaces {prompt}")
    r.add_argument("--stage2-recorded", help="replay stage-two replies from this file instead of a command")
    r.add_argument("--stage2-limit", type=int, help="run stage two on at most this many escalated items")
    r.add_argument("--stage2-timeout", type=float, default=STAGE2_TIMEOUT,
                   help="seconds before stopping a stage-two command (default: 60)")
    r.add_argument("--stage2-cost-per-call", type=float, help="USD per stage-two call (default: not metered)")
    r.add_argument("--record-stage1", help="write a stage-one replay file from this run")
    r.add_argument("--record-stage2", help="write a stage-two replay file from this run")
    r.add_argument("--limit", type=int, help="process only the first N items")
    r.set_defaults(func=cmd_run)
    q = sub.add_parser("report", parents=[shared], help="cost, latency and accuracy per stage from an output JSONL")
    q.add_argument("path", nargs="?")
    q.set_defaults(func=cmd_report)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    demo_stdout = io.StringIO() if args.demo else None
    try:
        for field, value, minimum, text in (
                ("--stage2-limit", getattr(args, "stage2_limit", None), 0, "0 or more"),
                ("--limit", getattr(args, "limit", None), 1, "1 or more"),
                ("--stage2-cost-per-call", getattr(args, "stage2_cost_per_call", None), 0, "0 or more"),
                ("--stage2-timeout", getattr(args, "stage2_timeout", None), 0, "greater than 0")):
            if value is not None and (not value >= minimum or
                                      (field == "--stage2-timeout" and not value > 0)):
                raise ValueError("{} must be {}".format(field, text))
        with contextlib.redirect_stdout(demo_stdout) if demo_stdout else contextlib.nullcontext():
            if args.demo:
                print(jev_client.DEMO_LABEL)
            if args.cmd is None:
                if not args.demo:
                    build_parser().print_help()
                    return 0
                args = build_parser().parse_args(["--demo", "run"] + (["--model", args.model] if args.model else []))
                out = cmd_run(args)
                print()
                result = cmd_report(argparse.Namespace(path=out))
            else:
                result = args.func(args)
        if demo_stdout:
            sys.stdout.write(demo_stdout.getvalue())
        return result if isinstance(result, int) else 0
    except jev_client.JevKeyMissing as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    except jev_client.JevError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2 if exc.status in (401, 403) or args.demo else 1
    except (jev_client.InputError, ValueError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
