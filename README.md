# jev-cascade

Run Jev as a cheap, recall-tuned first stage that answers many questions per item in one call, send only the uncertain band to a stronger model, and measure cost, latency and whether stage two is actually stronger.

![jev-cascade demo: stage one on 120 tickets, stage two on the uncertain ones, then the per-stage report](docs/demo.gif)

Interactive explainer: [docs/index.html](docs/index.html) (https://capcurious.github.io/jev-cascade/). Move four thresholds and watch 120 tickets move between acting and stage two.

```
$ python3 jev_cascade.py --demo        # abridged
DEMO (recorded response)
ran 120 items, 68 escalated

escalated: 68 of 120 (56.7%); stage two ran on 40, skipped 28, replies with a parse problem 0
stage one Jev  $0.00349    $0.0291 per 1,000 items
stage two      $0.00000    $0.0000   (not metered here: subscription)
median latency: stage one 0.19 s; stage two 4.02 s (40 items); end to end 0.20 s

field        s1 in act band       s1 on escalated      s2 on escalated      end to end           s2 vs s1
urgent       101/101 (100.0%)     36/40 (90.0%)        37/40 (92.5%)        116/120 (96.7%)      stronger
sentiment    49/74 (66.2%)        15/40 (37.5%)        20/40 (50.0%)        70/120 (58.3%)       stronger
```

Columns: stage one where it was sure; stage one versus stage two on the same escalated items; the final blend.

## What Jev is

Jev is a hosted decision model from TypeSafe (System One (TypeSafe's name for this family of fast decision models, after the fast and slow thinking distinction)). You send it a JSON state and plain-language questions of a fixed type: yes/no (`noul`, returns a probability), pick one (`choice`), or a 1 to 5 `score`. It answers with calibrated numbers and no prose. There are no explanations by design. One call can carry many questions about the same state, and it is small and fast: about 0.2 seconds a call here, $0.042 per million input tokens, output free.

That makes it programmable. The model returns a probability and your code owns the policy: act automatically above one number, send to a person between two, escalate below. You can change a threshold without re-running inference, and each question can have its own. This repo is the escalate path: what happens to the items Jev is not sure about.

## Why a cascade

A cheap, calibrated first stage handles the bulk; a strong, slow second stage sees only the uncertain band. Stage one is tuned for recall, meaning the policy is set so that few items that need a closer look slip through as confident answers. Stage two is any command you can call from a shell. The check that matters is the last one: on the items stage two received, is it actually more accurate than stage one was on those same items? An independent test on shell commands (reported by mizchi, 2026-10, https://github.com/mizchi/jev-playground) found a Sonnet second stage weaker than Jev alone, 21 of 24 correct against 23 of 24. `report` runs that check on your data and prints a warning when stage two is not stronger. A cascade whose second stage is no better is a cost and a delay, not a safety net.

## Install

Python 3.10 or newer, standard library only.

```
git clone https://github.com/CapCurious/jev-cascade && cd jev-cascade
python3 jev_cascade.py --demo
```

Or with uv: `uvx --from git+https://github.com/CapCurious/jev-cascade jev-cascade --demo`

## Quickstart (60 seconds)

1. Offline, no key: `python3 jev_cascade.py --demo`. It replays recorded stage-one and stage-two responses and prints `DEMO (recorded response)` first.
2. Live, with your own key (create one at https://console.typesafe.ai/keys). Stage two needs the `claude` CLI on your PATH, or pass your own command with `--stage2`:

```
export JEV_API_KEY=...        # TYPESAFE_API_KEY also works
python3 jev_cascade.py run examples/tickets.jsonl examples/questions.json examples/policy.json \
    --model jev-1.13.0 --stage2-limit 40 --out examples/run_live.jsonl
python3 jev_cascade.py report examples/run_live.jsonl
```

Stage one for the 120 sample tickets costs about $0.003 and takes about 25 seconds. Stage two takes 3 to 14 seconds per escalated ticket with the claude CLI, so `--stage2-limit 40` caps it at about three minutes. Pin a versioned model id as above; aliases such as `jev-latest` can change under you.

| Command | What it does |
|---|---|
| `run [ITEMS] [QUESTIONS] [POLICY]` | Stage one on every item, stage two on the escalated ones. Writes one JSONL row per item. |
| `report [OUTPUT]` | Cost, latency and accuracy per stage, and the stronger-second-stage check. |
| `--demo` | `run` then `report` on the recorded responses. No key, no network, no claude CLI. |

`run` flags: `--out FILE`, `--model ID`, `--limit N` (first N items), `--stage2 "CMD"`, `--stage2-recorded FILE` (replay stage-two replies), `--stage2-limit N`, `--stage2-cost-per-call USD`, `--record-stage1 FILE`, `--record-stage2 FILE` (save replay files from a live run).

## Input formats

Items are JSONL, one object per line: `{"id": "t001", "text": "...", "labels": {...}}`. Labels are optional and only used by `report`. The questions file maps a question id to a Jev question, and each question is answered in the same call:

```json
{"urgent": {"type": "noul", "instructions": "Is this support ticket urgent? ..."},
 "category": {"type": "choice", "instructions": "...", "criteria": {"billing": "...", "bug": "..."}},
 "sentiment": {"type": "score", "instructions": "...", "criteria": ["very negative", "negative", "neutral", "positive", "very positive"]}}
```

A `score` answer is a probability-weighted 0-based index into the criteria list (legend keys 0 to 4 for five criteria). This kit adds 1 for the 1 to 5 display, so an API score of 1.05 shows as level 2.

## How the cascade decides

Policy file (`examples/policy.json`, the same shape `jev-threshold-lab` writes):

```json
{"model": "jev-1.13.0",
 "fitted_on": {"n": 0, "date": "2026-10-18", "source": "default policy, not fitted; ..."},
 "questions": {"urgent": {"type": "noul", "act": 0.85, "review": 0.60, "metrics": {...}}},
 "note": "thresholds do not transfer; refit on your data"}
```

For a `noul` question the banded number is certainty, `max(p, 1 - p)`, so a confident no acts as readily as a confident yes. For `choice` and `score` it is the returned confidence. An item is in the act band at or above `act`, in review at or above `review` and below `act`, and escalates below `review`. A common starting point many integrations use is act 0.85 and review 0.60.

The cascade escalates an item when any question falls below its act line, review band included. Stage two answers all four questions, but it only replaces the stage-one answers that were below act; an answer stage one was sure about stays. If the stage-two reply is missing, malformed or invalid for a field, the stage-one answer stands for that field. The default policy here is unfitted. The tool that fits one on your own labeled data is [jev-threshold-lab](https://github.com/CapCurious/jev-threshold-lab); run it per question, then point `run` at the `policy.json` it writes.

## Stage two

The default command is `claude -p --model sonnet --setting-sources project`. The prompt goes to the command's standard input (or replaces `{prompt}` if the template has it), the command runs in an empty temporary directory with a 60 second timeout, and the reply is parsed defensively: the first JSON object in the text, fences and chatter tolerated, every field checked against the question (a boolean, one of the options, an integer in range). An invalid field falls back to stage one. Any command that reads a prompt and prints one JSON object works:

```
python3 jev_cascade.py run ... --stage2 "my-model-cli --json"
```

The `--setting-sources project` flag matters: without it a personal Claude Code configuration on the machine can change the answer format. The prompt carries the ticket text verbatim, so ticket text is an injection surface into stage two; use a stage two that has no tools.

## Cookbook: support-ticket triage

Four questions per ticket: `urgent` (noul), `needs_human` (noul), `category` (billing, bug, account, other), `sentiment` (score, five levels). Fixtures: 120 synthetic tickets generated by rules in `examples/make_fixtures.py`, with labels true by construction (a ticket is assembled from parts that each carry their label; no model wrote or checked them). About a quarter are ambiguous on purpose: a second topic after the main request, "URGENT!!!" on a pricing question, "no rush" in front of a real outage, a manager mentioned in passing, mixed-tone sentences.

Run 2026-10-18: stage one `jev-1.13.0`, stage two `claude -p --model sonnet --setting-sources project` (claude CLI 2.1.286), default policy (act 0.85, review 0.60 on every question), 120 tickets, 83,193 input tokens.

```
escalated: 68 of 120 (56.7%); stage two ran on 40, skipped 28, replies with a parse problem 0
cost           total       per 1,000 items
stage one Jev  $0.00349    $0.0291
stage two      $0.00000    $0.0000   (not metered here: subscription)
median latency: stage one 0.19 s; stage two 4.02 s (40 items); end to end 0.20 s (90th percentile 4.85 s)

field        s1 in act band       s1 on escalated      s2 on escalated      end to end           s2 vs s1
category     112/112 (100.0%)     40/40 (100.0%)       40/40 (100.0%)       119/120 (99.2%)      tied
needs_human  105/105 (100.0%)     40/40 (100.0%)       40/40 (100.0%)       120/120 (100.0%)     tied
sentiment    49/74 (66.2%)        15/40 (37.5%)        20/40 (50.0%)        70/120 (58.3%)       stronger
             within one level: s1 in act band 72/74 (97.3%), end to end 116/120 (96.7%)
urgent       101/101 (100.0%)     36/40 (90.0%)        37/40 (92.5%)        116/120 (96.7%)      stronger
escalated items, all fields pooled: stage one 131/160 (81.9%), stage two 137/160 (85.6%)
```
(report abridged; the full output includes a per-field section for the fields stage one was unsure about)

The end-to-end median hides a tail: the 90th percentile is 4.85 s because escalated items wait for stage two.

How to read it. The unfitted default policy sends 56.7% of tickets to stage two, which is too many for a cascade to pay off. Sentiment is the reason: 46 tickets fall below the act line on sentiment, 30 of the 68 escalations are sentiment alone, and a five-level tone score is the question where confidence is lowest. Per-question bands from the lab would bring the escalation share down. Stage two ran on the first 40 escalated tickets in id order; the other 28 kept their stage-one answers, which is why the end-to-end column is below what a full run could reach. On those 40, stage two was ahead by 6 of 160 field answers (137 against 131): clearly better on sentiment (13 of 28 against 8 of 28 on the fields stage one was unsure about), a tie on category and needs_human, one ticket better on urgent. With n=40 that is a lean, not a result. Stage two is a subscription call here, so its cost is zero in the table; it is not free in time (4.02 s median, about 21 times stage one).

An output row looks like this, abridged to two of the four question fields (sentiment and urgent):

```json
{"id": "t014", "stage": "stage2", "escalated": true,
 "stage1": {"sentiment": {"answer": 4, "certainty": 0.69, "band": "review"},
            "urgent": {"answer": false, "certainty": 0.99, "band": "act"}},
 "stage2": {"sentiment": 3, "urgent": false},
 "final": {"sentiment": 3, "urgent": false},
 "final_source": {"sentiment": "stage2", "urgent": "stage1"},
 "latency_s": {"stage1": 0.184, "stage2": 3.957}, "cost_usd": {"stage1": 2.8e-05, "stage2": 0.0}}
```

## Cookbook: tune one band, inference never reruns

The policy is code, so a band edit is a replay, not a new run. `examples/policy_tuned.json` lowers only sentiment (act 0.60, review 0.55), set by hand from the recorded run; it is not fitted. Both policies below read the same recorded stage-one responses (`examples/recorded_stage1.json`) and the same recorded stage-two replies, written to `examples/run_default.jsonl` and `examples/run_tuned.jsonl`:

```
python3 jev_cascade.py --demo run examples/tickets.jsonl examples/questions.json examples/policy_tuned.json --out examples/run_tuned.jsonl
python3 jev_cascade.py report examples/run_tuned.jsonl
```

| 120 synthetic tickets, 2026-10-18 | default (act 0.85) | tuned (sentiment act 0.60) |
|---|---|---|
| escalated to stage two | 68 (56.7%) | 46 (38.3%) |
| stage two had a recorded reply | 40 | 26 |
| end to end, all 480 field answers | 425 (88.5%) | 422 (87.9%) |
| end to end, sentiment | 70/120 (58.3%) | 67/120 (55.8%) |
| end to end, urgent, category, needs_human | unchanged | unchanged |

No model call was repeated: no Jev request and no `claude` call was made for either policy. Moving one band cut escalations by 22 tickets and cost 3 field answers, all of them sentiment. The stage-one answers alone score 419 of 480 (87.3%), so on this fixture both policies sit above stage one alone, by 6 and 3 answers. Stage two only has replies for the first 40 default escalations, so neither end-to-end figure is a full-run number. For bands fitted on your own labels, with precision and recall at each line, use [jev-threshold-lab](https://github.com/CapCurious/jev-threshold-lab).

## Limits and honesty

- Numbers: 2026-10-18, jev-1.13.0 versus claude sonnet (CLI 2.1.286), n=120 tickets, stage two on n=40 escalated.
- No explanations. Jev returns numbers, so the cascade can tell you where stage one is unsure, not why.
- The fixtures are synthetic, written by rules, and dated. Every number above is on 120 synthetic tickets with labels the generator's rules define, including the sentiment labels, which are a template author's reading of tone. Real tickets will look different.
- Thresholds do not transfer across datasets or model versions. The policy here is the community default, unfitted. Refit per question when the data, the question text or the model id changes, and pin a versioned id. The lab is the tool that fits one.
- Calibration is a population property, not a per-answer guarantee. One answer at 0.90 is not 90% likely to be right.
- Stage-two cost is not metered here. The claude CLI runs on a subscription, so the report prints zero; pass `--stage2-cost-per-call` if your stage two bills per call. Stage-two latency is wall time of the command and includes its startup.
- Text only (images are beta and not used). State is capped at 64k tokens per request.
- The stage-two comparison in the cookbook is on 40 tickets and one stage-two model. It shows how to measure, not that stage two wins in general.

## Development

```
python3 -m unittest discover -s tests                 # no key needed
JEV_LIVE=1 python3 -m unittest discover -s tests      # also runs stage one live on 5 items
python3 examples/make_fixtures.py                     # regenerate fixtures (seeded)
```

Expected last line: in a git checkout `OK (skipped=1)` (the live test, without a key); in a downloaded or exported tree `OK (skipped=2)` (the live test plus the git-export test, which needs a `.git` folder). `jev_client.py` is a shared client copied unchanged between the Jev kits; do not edit it here. Rebuild the cookbook numbers with the command in [EVAL.md](EVAL.md).

See [docs/index.html](docs/index.html) for the interactive explainer (GitHub Pages once published), [docs/HOW_IT_WAS_BUILT.md](docs/HOW_IT_WAS_BUILT.md) for how the kit was measured and what was not, and the skill under `.claude/skills/jev-cascade/` for agents. `python3 tools/make_explainer_data.py` re-embeds the recorded run into the page.

## License

MIT, see [LICENSE](LICENSE).
