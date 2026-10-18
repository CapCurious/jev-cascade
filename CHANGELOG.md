# Changelog

## Unreleased, 2026-10-18 (iteration 2 of the quality loop)

- Input validation: a missing file, a non-UTF8 file, a malformed JSONL line or a record missing a field ends in one "error: <path>:<line>: <what>" line and exit 2, never a traceback.
- Range checks: thresholds, costs, steps and limits outside their range end in one line naming the flag and the allowed range, exit 2.
- Fail fast: 10 s HTTP timeout; after 3 consecutive failed calls the run stops with the last cause.
- No clobber: `run --out` is written via a temp file then renamed; a failing run no longer truncates the previous file; an existing --out needs --force; `--stage2-timeout SECONDS` (default 60) bounds the stage-two command.
- README: cost in short dated sentences with stage two priced separately and labeled an estimate, "no key, offline" on the demo line, `noul` and the 64k state cap defined at first use, the stage-two alias named with the model id it resolved to.
- `run` writes to `run.jsonl` in the current folder by default (was the shipped `examples/run_live.jsonl`, which the no-clobber check would now refuse); the quickstart and cookbook write outside `examples/`.

## Unreleased, 2026-10-18 (iteration 1 of the quality loop)

- README cut from 2,398 to about 1,100 words: first screen leads with the stage-two-stronger check and its measured verdict; cost per 1,000 and 100,000 tickets with the stage-two assumption, and a "nothing to host" line; the Jev section is shared word for word with the sibling kits.
- jev_client: HTTP 401 or 403 raises one clear line naming JEV_API_KEY and the console URL; `run` stops on the first auth error with exit 2.
- Demo mode no longer answers an input that has no recording; it exits 2 with one line and no report.
- Report: stage two reads "not metered (subscription)" instead of $0.0000.
- Explainer: a "Repo on GitHub" link in the rail.
- Gate: tests `OK (skipped=1)`, demo identical except the not-metered line, privacy grep all classes zero except the public origin remote, leakage scan 0 findings, scorecard 13 of 15 on the working tree before the last one-word trim.

## v4 (2026-10-18)

Docs glosses from cold reads. No code changed.

What changed:
- README: first "System One" now carries a one-clause gloss.
- README: "community defaults" reworded to "a common starting point many integrations use".
- README: the cookbook report block is marked abridged (the per-field section for fields stage one was unsure about is not shown).

Gates (2026-10-18):
- tests: Ran 37 tests, OK (skipped=1)
- privacy scan: 0 findings
- name, path and secret grep: pass
- Em dashes across the folder: 0 files
- README.md: 189 lines
- Tag: v0.1.0

## v3 (2026-10-18)

Three README repairs from the cold read.

- Development section states both expected test endings as they print: `OK (skipped=1)` in a git checkout, `OK (skipped=2)` in a downloaded or exported tree.
- The example output row says it is abridged to two of the four question fields.
- A sentence under the full report says the end-to-end median hides a tail: 90th percentile 4.85 s, because escalated items wait for stage two.

Gates (2026-10-18):
- tests: Ran 37 tests, OK (skipped=1); in an exported tree (`git archive HEAD`, env limited to PATH and HOME): OK (skipped=2)
- privacy scan: 0 findings
- name, path and secret grep: pass
- Em dashes across the folder: 0 files
- README.md: 188 lines
- Tag: v0.1.0

## v2 (2026-10-18)

Explainer, demo GIF, skill, CI, fresh-tree test, two-policy cookbook, README cold-read repairs.

Decisions:
- Tune one band, inference never reruns: `examples/policy_tuned.json` lowers sentiment to act 0.60 and review 0.55 by hand, and both policies replay the same recorded responses. Escalated 68 of 120 (56.7%) against 46 of 120 (38.3%); end to end 425 of 480 (88.5%) against 422 of 480 (87.9%), all three lost answers on sentiment. Stage two replied on 40 against 26 tickets, so neither figure is a full run. Numbers are mirrored in EVAL.md and README.
- The explainer recomputes the report in the browser from `examples/run_default.jsonl` embedded as one JS constant (`tools/make_explainer_data.py`). At the default lines the page matches the printed report (116, 120, 119 and 70 of 120 per field); with sentiment at 0.60 it matches the tuned replay (46 escalated, 67 of 120 on sentiment). Its latency figure is the weighted average, 0.19 s times the non-escalated share plus 4.0 s times the escalated share, labeled an estimate.
- `tests/test_fresh_tree.py` exports tracked files with `git archive HEAD` and runs the demo run and report there with only PATH and HOME in the environment. It skips when the folder has no `.git` directory, as in a downloaded zip, so the documented test command still ends in OK.
- Cold-read repairs to README: the one-sentence purpose now names the recall-tuned first stage, many questions per call and the stronger-second-stage check; a Columns line under the hero table; a dated Numbers line in Limits; the mizchi citation carries its URL.
- The skill triggers on "cascade Jev then Claude", "only escalate the uncertain ones", "is the second stage actually stronger"; its pointer line is last.

Trigger test (a small model via `claude -p --setting-sources project`, 60 s timeout, asked to name the skill it would invoke):
- "cascade Jev then Claude on these support tickets": SKILL=jev-cascade
- "only escalate the uncertain ones to the stronger model": SKILL=jev-cascade
- "is the second stage actually stronger than Jev?": SKILL=jev-cascade
- "summarize this PDF": SKILL=none
- "write a cover letter": SKILL=none

Gates (2026-10-18):
- tests: Ran 37 tests in 0.725s, OK (skipped=1); in an exported tree with no .git: OK (skipped=2)
- privacy scan: 0 findings
- name, path and secret grep: pass
- Python 3.10 parse (`ast.parse(..., feature_version=(3, 10))`): ok for all six .py files
- Em dashes across the folder: 0 files
- docs/index.html: 44,281 bytes (limit 150 KB), 577 words on screen (limit 600)
- docs/demo.gif: 186,630 bytes (limit 2 MB), 15.6 s (limit 25 s), 1060 by 640, two ffmpeg frames read legibly
- Explainer in the built-in browser over `python3 -m http.server`: light, dark and 375 px mobile screenshots taken, no horizontal scroll at 375, console 0 errors and 0 warnings, server stopped
- jev_client.py checksum matches the shared client: OK

Not done: the second cold-reader pass on the repaired README, a refit policy from jev-threshold-lab, a run with stage two on all 68 escalated tickets, the v0.1.0 tag.

## v1 (2026-10-18)

First runnable version: `run`, `report`, `--demo`, fixture generator, 36 tests, README, EVAL.

Decisions:
- Escalation is per item (any question below act, review band included), replacement is per field: stage two answers all four questions but only replaces the stage-one answers that were below act. A confident stage-one field is never overwritten by a slower, weaker-calibrated stage.
- A missing, malformed or invalid stage-two field falls back to the stage-one answer for that field and is counted wrong in the stage-two accuracy column, so a flaky second stage cannot look good by failing quietly.
- The stronger-second-stage check compares stage one and stage two on the same escalated items, pooled over fields, and prints a warning when stage two is not strictly ahead. Per field it prints stronger, tied or WEAKER.
- A score answer is a probability-weighted 0-based index into the criteria list, so the 1 to 5 display value is round(score) + 1. Sentiment also reports within-one-level accuracy because five-level exact match on synthetic labels is harsh.
- Stage two receives the prompt on stdin (or in place of `{prompt}`) and runs in an empty temporary directory with `--setting-sources project`; without it a personal configuration on the machine changes the answer format.
- `--stage2-limit` was needed: the unfitted default policy (act 0.85, review 0.60) escalated 68 of 120 tickets, so stage two ran on the first 40 escalated tickets and the other 28 kept their stage-one answers. The report says so.
- `--model` and `--demo` are accepted before or after the subcommand.
- The report adds the 90th percentile of end-to-end latency because the median hides the cascade's slow tail.
- `tools/` stays empty in v1: the live run is the evaluation, so there is no separate compare script as in jev-threshold-lab.

Gates (2026-10-18):
- tests: Ran 36 tests in 0.579s, OK (skipped=1)
- tests with JEV_LIVE=1: Ran 36 tests in 1.624s, OK
- privacy scan: 0 findings
- name, path and secret grep: pass
- Python 3.10 parse (`ast.parse(..., feature_version=(3, 10))`): ok for all four .py files
- Em dashes across the folder: 0 files
- jev_client.py checksum matches the shared client: OK

Not yet built: docs/index.html, docs/demo.gif, docs/HOW_IT_WAS_BUILT.md, the skill, the CI workflow, the cold-reader pass, a refit policy from jev-threshold-lab, and a run with stage two on all 68 escalated tickets.
