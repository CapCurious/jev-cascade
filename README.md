# jev-cascade
Jev as a cheap first stage, a stronger model only on items it is unsure about, and a per-stage report of cost, latency, accuracy.

Its check: is stage two actually stronger on the escalated items? Measured 2026-10-18 (n=120 synthetic tickets, `jev-1.13.0`, then claude CLI 2.1.286 `--model sonnet` on the 40 escalated): yes, narrowly, 137 of 160 field answers against stage one's 131.

![jev-cascade demo: run, then report](docs/demo.gif)
## Quickstart
```
python3 jev_cascade.py --demo          # no key, offline
export JEV_API_KEY=YOUR_KEY        # from console.typesafe.ai/keys; TYPESAFE_API_KEY also works
python3 jev_cascade.py run examples/tickets.jsonl examples/questions.json examples/policy.json --model jev-1.13.0 --stage2-limit 40 --out examples/run_live.jsonl
```

Stage one, measured 2026-10-18 on `jev-1.13.0` at the published $0.042 per million input tokens: 1,000 tickets cost about $0.029 and 3.2 minutes serial; 100,000 about $2.90 and 5.3 hours. Stage two is whatever model you point the command at; the kit prices it through `--stage2-cost-per-call`. At the default policy about 567 of 1,000 tickets escalate. Stage two alone on those, at claude sonnet's API list price, is about $2.46 and 41 minutes serial per 1,000 tickets, so about $246 and 68 hours per 100,000. An estimate: the claude CLI is a subscription. Demo mode is free and offline. Live mode sends each ticket's text to TypeSafe and the escalated ones to your stage-two command.

Nothing to host: the [explainer](https://capcurious.github.io/jev-cascade/) is a static page on GitHub Pages and the kit runs locally; there is no browser playground because the Jev API rejects browser origins (a preflight from github.io answered 400 Disallowed CORS origin on 2026-10-18).

## What Jev is

Jev is a hosted decision model from TypeSafe. You send it a text and one or more typed questions (yes or no, pick one from a list, or a score from 1 to 5) and it returns a probability for each answer, with no prose.

The probability is the interface. Your code sets the threshold, so the same answer can mean act, review or escalate depending on what a wrong call costs you. Calibration is a property of a population of answers, measured on a dated sample, not a guarantee on any single answer.

## Install and commands

Python 3.10 or newer, standard library only: `git clone https://github.com/CapCurious/jev-cascade && cd jev-cascade`, or `uvx --from git+https://github.com/CapCurious/jev-cascade jev-cascade --demo`. `run [ITEMS] [QUESTIONS] [POLICY]` writes one JSONL row per item (`run --help` lists the flags). `report [OUTPUT]`, as in `python3 jev_cascade.py report examples/run_live.jsonl`, prints cost, latency and accuracy per stage plus the stronger-second-stage check.

## Threshold policy

`examples/policy.json` (the shape `jev-threshold-lab` writes) sets `act` and `review` per question. The banded number is certainty, `max(p, 1 - p)`, for `noul` (yes or no), so a confident no acts like a confident yes; for `choice` and `score` it is the returned confidence. At or above `act` an item is acted on, from `review` to `act` it goes to review, below `review` it escalates; act 0.85 and review 0.60 are a common starting point. Any question below act escalates the item, and stage two replaces only those answers; an invalid stage-two field keeps stage one. jev-threshold-lab fits them on your labeled data.

## Stage two

The default command, `claude -p --model sonnet --setting-sources project`, needs the `claude` CLI. It reads the prompt on standard input (or in place of `{prompt}`) and runs in an empty temporary directory with a 60 second timeout; the reply's first JSON object is checked per field. Without `--setting-sources project` a personal Claude Code configuration can change the answer format. Ticket text can inject instructions, so give stage two no tools. Any command that reads a prompt and prints one JSON object works:

```
python3 jev_cascade.py run ... --stage2 "my-model-cli --json"
```

## Cookbook: support-ticket triage

Questions: `urgent` and `needs_human` (noul), `category` (choice), `sentiment` (score, five levels), on 120 synthetic tickets from `examples/make_fixtures.py`, labels true by construction; Run 2026-10-18: `jev-1.13.0`, then the default stage two (claude CLI 2.1.286), default policy, 83,193 input tokens. 56.7% is the unfitted default; the tuned policy below escalates 38.3%.

```
escalated: 68 of 120 (56.7%); stage two ran on 40, skipped 28, replies with a parse problem 0
stage two      not metered            (subscription)
field        s1 in act band       s1 on escalated      s2 on escalated      end to end           s2 vs s1
sentiment    49/74 (66.2%)        15/40 (37.5%)        20/40 (50.0%)        70/120 (58.3%)       stronger
urgent       101/101 (100.0%)     36/40 (90.0%)        37/40 (92.5%)        116/120 (96.7%)      stronger
escalated items, all fields pooled: stage one 131/160 (81.9%), stage two 137/160 (85.6%)
```
(`python3 jev_cascade.py --demo` output, abridged; category and needs_human tie at 100%)

Stage two ran on the first 40 escalated tickets; the other 28 kept stage one. Its lead of 6 came from sentiment and one urgent ticket; its median, 4.02 s, is about 21 times stage one's.

Tuning a band reruns no inference: `examples/policy_tuned.json` sets sentiment to act 0.60, review 0.55 and replays the recorded responses:

```
python3 jev_cascade.py --demo run examples/tickets.jsonl examples/questions.json examples/policy_tuned.json --out examples/run_tuned.jsonl
python3 jev_cascade.py report examples/run_tuned.jsonl
```

Escalated 46 (38.3%, tuned) against 68 (56.7%, unfitted default); end to end 422 of 480 answers (87.9%) against 425 (88.5%), all 3 lost on sentiment; stage one alone 419 (87.3%). Neither is a full-run number.

## Limits

- Numbers: 2026-10-18, jev-1.13.0 versus claude sonnet (CLI 2.1.286), n=120 tickets, stage two on n=40 escalated.
- No explanations: the cascade shows where stage one is unsure, never why.
- Fixtures are synthetic, rule-labeled and dated (120 tickets; sentiment labels are a template author's reading of tone). Real tickets will look different.
- Thresholds do not transfer across datasets or model versions; this policy is unfitted. Refit per question when the data, question text or model id changes, and pin a versioned id.
- Calibration is a population property: one answer at 0.90 is not 90% likely to be right.
- Stage-two cost is not metered (the claude CLI is a subscription); pass `--stage2-cost-per-call` if yours bills per call. Stage-two latency is wall time, startup included.
- Text only (images are beta and not used). State is capped at 64k tokens per request.
- The comparison covers 40 tickets and one stage-two model, so it demonstrates the measurement only.

## Development

```
python3 -m unittest discover -s tests                 # no key needed
JEV_LIVE=1 python3 -m unittest discover -s tests      # also runs stage one live on 5 items
python3 examples/make_fixtures.py                     # regenerate fixtures (seeded)
```

Expected last line: `OK (skipped=1)` in a checkout, `OK (skipped=2)` in a downloaded tree. [EVAL.md](EVAL.md) rebuilds the numbers, [docs/HOW_IT_WAS_BUILT.md](docs/HOW_IT_WAS_BUILT.md) the method; `python3 tools/make_explainer_data.py` re-embeds the run into the explainer.

Jev kits: [jev-threshold-lab](https://github.com/CapCurious/jev-threshold-lab) fits act and review lines per question; [jev-role-ranker](https://github.com/CapCurious/jev-role-ranker) ranks job postings, flags, never rejects.

## License

MIT, see [LICENSE](LICENSE).
