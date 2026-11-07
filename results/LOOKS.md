# Held-out looks

Every time the held-out vulture scoring set (deployments from 2013) has
been scored, or its figures seen, newest last. `make score WHY="..."` is
the only command that rescores it, and it appends one entry here: the
date, the commit scored, the reason given and the headline figures under
each arrival scenario. `make results` and `make evaluate` read the last
scored file back unchanged. Do not edit entries by hand; add a note below
an entry instead.

A held-out set stops being held out the more often it is looked at,
especially when a decision follows a look. Figures here are the
evidence for how far the published held-out results can be trusted.

The entries up to 2026-10-24 were reconstructed on 2026-10-30 from the
commit trail and the committed results file
(`results/evaluation/vultures-scoring.json`, at
`results/vultures/evaluation-scoring.json` before `9f9e388`). Dates the
commits cannot confirm are marked unconfirmed. The commit `9f9e388`
only moved the file, so it is not a look.

Columns: mortality and potential-death alerts counted as true or false
against the labels (ambiguous tracks left out), precision as true over
true plus false, false mortality alerts per animal-month, and carcass
deaths flagged by the mortality alert within the 92.5 h mark.

## 2026-10-18, 0c3a5be

First scoring, after the mortality and gap thresholds were frozen on the
tuning set. Precision was not computed yet, so those cells are empty.

| Scenario | Mortality true / false | Mortality precision | False mortality per animal-month | Carcasses flagged by the mark | Potential death true / false | Potential death precision |
|---|---|---|---|---|---|---|
| Ideal | – / 191 | – | 0.389 | 4 of 5 | – / – | – |
| GSM | – / 190 | – | 0.387 | 3 of 5 | – / – | – |
| Satellite, daily | – / 191 | – | 0.389 | 3 of 5 | – / – | – |
| Satellite, 2-day | – / 191 | – | 0.389 | 3 of 5 | – / – | – |

## 2026-10-18, 99db483

Second look, 14 minutes after the first: added the priority alert, then
called `likely_death` (renamed `potential_death` in `f0a6df9`; shown
under that name here), and the precision metric. The alert has no tuned
parameter of its own. Mortality figures are unchanged from the first look.

| Scenario | Mortality true / false | Mortality precision | False mortality per animal-month | Carcasses flagged by the mark | Potential death true / false | Potential death precision |
|---|---|---|---|---|---|---|
| Ideal | 5 / 191 | 2.6% | 0.389 | 4 of 5 | 5 / 17 | 22.7% |
| GSM | 5 / 190 | 2.6% | 0.387 | 3 of 5 | 5 / 19 | 20.8% |
| Satellite, daily | 5 / 191 | 2.6% | 0.389 | 3 of 5 | 5 / 10 | 33.3% |
| Satellite, 2-day | 5 / 191 | 2.6% | 0.389 | 3 of 5 | 5 / 9 | 35.7% |

## Date unconfirmed (after 2026-10-18, before 2026-10-23), no commit

Third look: a candidate "silent while still" priority alert (a gap on a
collar still for 14 h or more). It was scored on this set and rejected,
partly because it cut potential-death precision here from 23% to 15%,
so a decision was made on held-out figures. The candidate was removed
before any commit, so no results file records the look; the figure
comes from the README's limitations, first committed in `a38b813`
(2026-10-23), and `docs/ASSUMPTIONS.md`. Only that one figure was
recorded.

## 2026-10-22, f0a6df9

Fourth look: the 75 m leaving radius for the mortality alert (chosen on
the tuning set) and the `likely_death` to `potential_death` rename. The
rerun moved held-out figures: mortality alerts that had flapped merged,
satellite carcasses flagged by the mark rose from 3 to 4 of 5, and
potential-death precision from 22.7% to 28.6% (ideal). The commits
cannot confirm whether held-out figures were seen before the radius was
chosen.

| Scenario | Mortality true / false | Mortality precision | False mortality per animal-month | Carcasses flagged by the mark | Potential death true / false | Potential death precision |
|---|---|---|---|---|---|---|
| Ideal | 6 / 186 | 3.1% | 0.378 | 4 of 5 | 6 / 15 | 28.6% |
| GSM | 6 / 184 | 3.2% | 0.374 | 4 of 5 | 6 / 18 | 25.0% |
| Satellite, daily | 6 / 186 | 3.1% | 0.378 | 4 of 5 | 6 / 8 | 42.9% |
| Satellite, 2-day | 6 / 186 | 3.1% | 0.378 | 4 of 5 | 6 / 7 | 46.2% |

## 2026-10-24 (unconfirmed), no commit

Fifth look: a review of the mortality alert's precision reproduced the
`f0a6df9` figures exactly. Nothing was rescored or changed, but the
set's figures were seen again, and the redesign that followed uses its
base rate (one carcass per 98 animal-months). The date comes from the
review's notes, which are not in git.

## 2026-10-31, 6b7dec7 plus uncommitted changes

Step 1.3: add precision intervals (Wilson; bootstrap by bird), the base-rate ceiling, gap-only and random baselines and a per-bird false-alert table; no detector change.

| Scenario | Mortality true / false | Mortality precision [Wilson 95%; by bird 95%] | Ceiling | False mortality per animal-month | Carcasses flagged by the mark | Potential death true / false | Potential death precision |
|---|---|---|---|---|---|---|---|
| Ideal | 6 / 186 | 3.1% [1.4-6.6%; by bird 0.9-8.0%] | 2.6% | 0.378 | 4 of 5 | 6 / 15 | 28.6% |
| GSM | 6 / 184 | 3.2% [1.5-6.7%; by bird 0.9-8.1%] | 2.6% | 0.374 | 4 of 5 | 6 / 18 | 25.0% |
| Satellite, daily | 6 / 186 | 3.1% [1.4-6.6%; by bird 0.9-8.0%] | 2.6% | 0.378 | 4 of 5 | 6 / 8 | 42.9% |
| Satellite, 2-day | 6 / 186 | 3.1% [1.4-6.6%; by bird 0.9-8.0%] | 2.6% | 0.378 | 4 of 5 | 6 / 7 | 46.2% |

## 2026-11-07, 6edb852 plus uncommitted changes

Added the tag-event label and three-way scoring (five birds: three tuning, two here; credited for mortality and gap, wrong for potential death). Run on uncommitted changes on top of the commit shown. The set is already spent: figures are reported as seen, not as validation.

| Scenario | Mortality true + tag event / false | Mortality precision [Wilson 95%; by bird 95%] | Ceiling | False mortality per animal-month | Carcasses flagged by the mark | Potential death true / false | Potential death precision |
|---|---|---|---|---|---|---|---|
| Ideal | 6 + 2 / 185 | 4.1% [2.1-8.0%; by bird 1.5-10.0%] | 2.6% | 0.376 | 4 of 5 | 6 / 16 | 27.3% |
| GSM | 6 + 2 / 183 | 4.2% [2.1-8.0%; by bird 1.5-10.2%] | 2.6% | 0.372 | 4 of 5 | 6 / 19 | 24.0% |
| Satellite, daily | 6 + 2 / 185 | 4.1% [2.1-8.0%; by bird 1.5-10.0%] | 2.6% | 0.376 | 4 of 5 | 6 / 9 | 40.0% |
| Satellite, 2-day | 6 + 2 / 185 | 4.1% [2.1-8.0%; by bird 1.5-10.0%] | 2.6% | 0.376 | 4 of 5 | 6 / 8 | 42.9% |
