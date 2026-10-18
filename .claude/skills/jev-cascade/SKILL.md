---
name: jev-cascade
description: Run Jev, a hosted decision model, as a cheap first stage on every item and send only the uncertain ones to a stronger model, then measure whether the second stage is actually stronger. Use when the user says "cascade Jev then Claude", "only escalate the uncertain ones", or "is the second stage actually stronger". Not for summarizing documents or writing text.
---

# jev-cascade

Two stages. Stage one is Jev: four typed questions per item in one call, answered with calibrated
numbers and no prose (about 0.2 seconds, about $0.03 per 1,000 tickets). Stage two is any shell command,
by default the `claude` CLI, and it sees only the items where Jev was unsure. `report` then says
whether stage two beat stage one on those same items, and prints a warning when it did not.

## When to use

- The user has many items (JSONL) and wants a fast first pass, with a stronger model only where
  the first pass is unsure.
- The user wants to know what the second stage costs in time and money, or whether it helps at all.
- The user wants to move a threshold and see who escalates without paying for new model calls.

## When not to use

- One item that needs a written answer. Jev returns numbers, not explanations.
- Fitting thresholds on labeled data: that is jev-threshold-lab. This kit runs a policy it wrote.
- Images, or more than 64k tokens of state per call.

## Commands

Run from the kit directory. Python 3.10 or newer, standard library only.

```
python3 jev_cascade.py --demo
export JEV_API_KEY=YOUR_KEY    # TYPESAFE_API_KEY also works
python3 jev_cascade.py run ITEMS.jsonl QUESTIONS.json POLICY.json --model jev-1.13.0 --stage2-limit 40 --out run.jsonl
python3 jev_cascade.py report run.jsonl
```

- `--demo` replays recorded stage-one and stage-two responses, needs no key, no network and no
  `claude` CLI, and prints `DEMO (recorded response)` first. Offer it first.
- `--stage2 "CMD"` swaps the second stage: the command reads the prompt on stdin and prints one JSON object.
- Pin a versioned model id; aliases move. Never print or log the key.

## Reading the result

- An item escalates when any question falls below its act line; stage two replaces only the
  answers stage one was unsure about. A bad stage-two field falls back to stage one.
- The last column of the report says stronger, tied or WEAKER per field. Report WEAKER plainly.
- Thresholds in `examples/policy.json` are unfitted community defaults and do not transfer.

Questions and why each is narrow: references/questions.md. How the numbers were measured: references/eval.md.
