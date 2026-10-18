# EVAL

Reproduce from a fresh clone with a Jev key and the `claude` CLI on your PATH (about four minutes, mostly stage two):

```
python3 jev_cascade.py run examples/tickets.jsonl examples/questions.json examples/policy.json \
    --model jev-1.13.0 --stage2-limit 40 \
    --record-stage1 examples/recorded_stage1.json --record-stage2 examples/recorded_stage2.json \
    --out examples/run_live.jsonl
python3 jev_cascade.py report examples/run_live.jsonl
```

Offline, the same report from the recorded responses: `python3 jev_cascade.py --demo`.

## Setup

Run date 2026-10-18. Stage one: Jev `jev-1.13.0`, one call per ticket with four questions (`urgent`, `needs_human`, `category`, `sentiment`), 120 calls, 83,193 input tokens, 23.2 s of API time. Stage two: `claude -p --model sonnet --setting-sources project` (claude CLI 2.1.286, `sonnet` is an alias the CLI resolves), run from an empty temporary directory, 60 s timeout. Policy: `examples/policy.json`, act 0.85 and review 0.60 on every question, unfitted.

Data: 120 synthetic tickets from `examples/make_fixtures.py` (seed 7). Labels come from the generator's rules, never from a model, so this is not a model grading a model. Escalation rule: any question below its act line. Stage two replaces only the fields that were below act; other fields keep stage one. Stage two was capped with `--stage2-limit 40`: 68 tickets escalated, stage two ran on the first 40 in id order, the other 28 kept their stage-one answers.

## Result

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

only the fields stage one was unsure about (below the act band)
category     stage one 4/4 (100.0%)   stage two 4/4 (100.0%)
needs_human  stage one 7/7 (100.0%)   stage two 7/7 (100.0%)
sentiment    stage one 8/28 (28.6%)   stage two 13/28 (46.4%)
urgent       stage one 8/12 (66.7%)   stage two 9/12 (75.0%)

escalated items, all fields pooled: stage one 131/160 (81.9%), stage two 137/160 (85.6%)
```

The stronger-second-stage check did not fire: pooled over the 40 tickets stage two received, it scored 137 of 160 field answers against stage one's 131 of 160, so no warning was printed. The margin is 6 answers on 40 tickets and comes from sentiment (13 against 8 of 28 below-act fields); category and needs_human are tied at 100%, and urgent differs by one ticket.

## Two-policy replay (tune one band, inference never reruns)

Date 2026-10-18. Same recorded responses, two policies, no model call repeated: stage one replays `examples/recorded_stage1.json` (`jev-1.13.0`), stage two replays `examples/recorded_stage2.json` (`claude -p --model sonnet --setting-sources project`) where a reply exists and is skipped otherwise. The tuned policy, `examples/policy_tuned.json`, lowers sentiment to act 0.60 and review 0.55 by hand; the other three questions are unchanged. It is not fitted.

```
python3 jev_cascade.py --demo run examples/tickets.jsonl examples/questions.json examples/policy.json --out examples/run_default.jsonl
python3 jev_cascade.py --demo run examples/tickets.jsonl examples/questions.json examples/policy_tuned.json --out examples/run_tuned.jsonl
python3 jev_cascade.py report examples/run_default.jsonl
python3 jev_cascade.py report examples/run_tuned.jsonl
```

| | default | tuned |
|---|---|---|
| escalated | 68 of 120 (56.7%) | 46 of 120 (38.3%) |
| stage two ran on / skipped | 40 / 28 | 26 / 20 |
| end to end, all 480 field answers | 425 (88.5%) | 422 (87.9%) |
| end to end, sentiment | 70/120 (58.3%) | 67/120 (55.8%) |
| end to end, sentiment within one level | 116/120 (96.7%) | 116/120 (96.7%) |
| end to end, urgent | 116/120 (96.7%) | 116/120 (96.7%) |
| median latency, end to end | 0.20 s | 0.19 s |
| stronger-second-stage check, pooled on escalated items | 137 against 131 of 160 | 88 against 84 of 104 |

Stage one alone scores 419 of 480 (87.3%). The tuned band removes 22 escalations and costs 3 sentiment answers, because sentiment answers between 0.60 and 0.85 certainty are now acted on without stage two and are right less often than stage two would have been. The comparison is not a verdict on either policy: stage two only has recorded replies for the first 40 default escalations, so both end-to-end figures understate what a full run would reach, and the tuned run lost 14 of those replies to its own smaller escalation set. Synthetic tickets, n=120, one run.

## Reading it

- The default policy escalates 56.7% of tickets, 30 of them on sentiment alone. At that share the cascade saves little against calling the strong stage on everything; per-question bands from jev-threshold-lab are the lever.
- Sentiment exact-match is low even inside the act band (66.2%) while within-one-level is 97.3%: the model's tone reading and the generator's template labels disagree by one step, which is a property of five-level scores on synthetic labels.
- End-to-end accuracy is below its ceiling because 28 escalated tickets never reached stage two.
- Stage-two cost is zero in the table because the claude CLI is a subscription, not because it is free. It costs time: 4.02 s median against 0.19 s.
- Everything here is synthetic, n is 120 (40 for the comparison), one stage-two model, one run. Do not quote it as a general result.
