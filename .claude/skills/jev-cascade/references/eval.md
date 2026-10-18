# How EVAL.md was produced

Date 2026-10-18. Stage one `jev-1.13.0`, stage two `claude -p --model sonnet --setting-sources project`
(claude CLI 2.1.286), 120 synthetic tickets. The tables are in EVAL.md at the repository root; this is the method.

1. Fixtures. `python3 examples/make_fixtures.py` writes 120 tickets from a seeded generator (seed 7).
   Labels come from the generator's rules, never from a model, so no model grades another model. About a
   quarter of the tickets mix signals on purpose.
2. Live run. One Jev call per ticket (120 calls, 83,193 input tokens), stage two on the first 40
   escalated tickets in id order (`--stage2-limit 40`), both recorded to `examples/recorded_stage1.json`
   and `examples/recorded_stage2.json`, which `--demo` and the tests replay.
3. Two-policy replay. `examples/policy.json` and `examples/policy_tuned.json` (sentiment act 0.60, review
   0.55, set by hand) run against the same recordings, so no model call is repeated. Results are in
   `examples/run_default.jsonl` and `examples/run_tuned.jsonl`.
4. The check. `report` compares stage one and stage two on the same escalated items, pooled over fields.
   At the default policy stage two scored 137 of 160 against 131; with n=40 that is a lean, not a result.
5. Not measured: stage two on all 68 escalated tickets, real tickets, stage-two cost (subscription).
