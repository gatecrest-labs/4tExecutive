# Hygiene Score reading 0.0 — investigation

## Summary

The Hygiene Score badge on the 4tExecutive dashboard is showing **0.0** for
the `Demo-test` (4thealth-plus) source. This is not a display bug and not a
missing-data issue — the hygiene sweep completed successfully and 4tExecutive
is displaying the value 4thealth-plus actually computed. The scoring formula
itself, in 4thealth-plus, produces 0.0 (clamped from a negative raw score)
whenever a small rule set has more per-check findings than it has rules —
which is close to guaranteed on a demo/lab fleet with only a handful of
rules. This document is for review, not a proposed fix — no code in
4thealth-plus was changed.

## Where the score is computed

`app/executive_summary_cache.py` in the **4thealth-plus** repo
(`_run_hygiene_sweep`, calling `_hygiene_score`):

```python
_HYGIENE_CHECKS = ["unnamed", "unlogged", "disabled", "expired", "unhit"]

def _hygiene_score(total_findings: int, total_policies: int) -> float | None:
    if total_policies == 0:
        return None
    score = 100 * (1 - total_findings / total_policies)
    return round(max(0.0, min(100.0, score)), 1)
```

`total_findings` is `len(run_checks(policies, _HYGIENE_CHECKS))` summed
across every policy package in every ADOM — i.e. it's a count of
**(policy, failed-check) pairs**, not a count of distinct policies with at
least one issue. A single rule that is both unnamed *and* never hit
contributes 2 to `total_findings`, not 1.

`total_policies` is the raw count of policies swept (7, in this environment
— matches the `Total Rules` widget).

## The actual numbers (this environment, 2026-09-01 snapshot)

From the stored `rule_findings_by_type` breakdown:

| check      | count |
|------------|------:|
| unnamed    | 4     |
| unlogged   | 0     |
| disabled   | 0     |
| expired    | 0     |
| unhit      | 7     |
| **sum (= `total_findings`)** | **11** |

```
total_policies = 7
score = 100 * (1 - 11 / 7)
      = 100 * (1 - 1.571...)
      = -57.1
clamped to [0, 100] → 0.0
```

## Root cause

The formula assumes a defect-rate shape (`findings / policies`, scaled to a
0–100 "percent clean" score) that implicitly expects at most ~1 finding per
policy on average. But `run_checks` can flag the **same policy** against
**multiple** checks in `_HYGIENE_CHECKS` simultaneously (e.g. a rule can be
both unnamed and never-hit at once), so `total_findings` is not
upper-bounded by `total_policies`. With only 7 policies, it takes very
little real-world messiness — here, 4 unnamed + 7 unhit rules, on rules that
overlap — to push `total_findings` past `total_policies` and drive the raw
score negative, at which point the clamp floors it at 0.0 regardless of how
negative the raw score actually was. A fleet with 700 rules and the same
*rate* of issues (400 unnamed, 700 unhit) would show the identical 0.0,
while one with 7000 rules and a worse absolute count of the same issues
could score much higher — the formula is not scale-invariant in a stable
way for small rule counts, which is exactly the demo-lab situation here.

## Options worth considering (no recommendation made — for your review)

1. **Normalize by findings capacity, not raw ratio.** e.g.
   `findings / (policies * len(_HYGIENE_CHECKS))` — bounds the denominator
   by the maximum possible findings (every policy failing every check),
   so the score can't go negative and stays meaningful at any fleet size.
2. **Count policies-with-a-finding, not raw finding occurrences.** Cap each
   policy's contribution to `total_findings` at 1 regardless of how many
   checks it fails — turns this into a true "% of clean policies" score.
3. **Floor before scaling, not after.** Clamp the *ratio* itself (e.g. at
   1.0) before the `100 * (1 - ratio)` step, so scores compress toward 0
   gracefully rather than any ratio > 1 collapsing to the same flat 0.0 —
   loses the ability to distinguish "somewhat bad" from "very bad" fleets.
4. **Add a minimum-fleet-size guard.** Report the score as `None`
   ("insufficient data" / pending, the same treatment 4tExecutive already
   gives a not-yet-run sweep) below some policy-count threshold, since a
   7-rule fleet is arguably too small for this ratio to be a meaningful
   signal either way.
5. **Leave the formula as-is; adjust expectations for small fleets.**
   Document that the score is only meaningful past some fleet size, and
   treat 0.0 on a small lab/demo environment as expected rather than
   alarming.

Options 1 and 2 are the least disruptive (same inputs, same output range,
no new "insufficient data" state to handle downstream) and would both stop
the score from bottoming out at 0.0 simply because a small fleet has more
issues-per-rule than 1. Options 3 and 4 involve a behavior/UX decision
(losing signal, or introducing a new pending-like state) that's worth a
product call rather than a code call.
