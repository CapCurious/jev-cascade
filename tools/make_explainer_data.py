"""Embed the recorded cascade run into docs/index.html as one JS constant.

Reads examples/run_default.jsonl (the default-policy replay of the recorded responses) and rewrites
the block between the DATA markers in docs/index.html. Offline, standard library only.

  python3 tools/make_explainer_data.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "docs", "index.html")
START, END = "/*DATA START*/", "/*DATA END*/"
FIELDS = ["urgent", "needs_human", "category", "sentiment"]
MAX_TEXT = 140


def build():
    with open(os.path.join(ROOT, "examples", "recorded_stage1.json"), "r", encoding="utf-8") as fh:
        rec = json.load(fh)
    with open(os.path.join(ROOT, "examples", "tickets.jsonl"), "r", encoding="utf-8") as fh:
        tickets = {json.loads(l)["id"]: json.loads(l) for l in fh if l.strip()}
    with open(os.path.join(ROOT, "examples", "run_default.jsonl"), "r", encoding="utf-8") as fh:
        runs = [json.loads(l) for l in fh if l.strip()]
    rows, tokens = [], sum(r["usage"]["input_tokens"] for r in rec["records"])
    for r in runs:
        s1 = r["stage1"]
        s2 = r["stage2"]
        text = tickets[r["id"]]["text"]
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT - 3].rstrip() + "..."
        rows.append([
            r["id"], text,
            [s1[q]["certainty"] for q in FIELDS],
            [s1[q]["answer"] for q in FIELDS],
            None if s2 is None else [s2.get(q) for q in FIELDS],
            [r["labels"][q] for q in FIELDS],
        ])
    return {"model": rec["model"], "recorded": rec["recorded_on"], "inputTokens": tokens,
            "pricePerMillion": 0.042, "fields": FIELDS, "rows": rows}


def main():
    data = build()
    block = "{}\nconst DATA = {};\n{}".format(START, json.dumps(data, separators=(",", ":")), END)
    with open(PAGE, "r", encoding="utf-8") as fh:
        page = fh.read()
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(page):
        raise SystemExit("DATA markers not found in docs/index.html")
    page = pattern.sub(lambda m: block, page)
    with open(PAGE, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("wrote {} rows, {} input tokens, {} bytes of page".format(
        len(data["rows"]), data["inputTokens"], len(page.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
