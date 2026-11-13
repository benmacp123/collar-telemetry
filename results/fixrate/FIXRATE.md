# Fix-rate cue (step 3.3)

Fitted on tuning birds only, under the experiment file's scenarios.
Each group counts equally: the shares are the mean of the vulture and
stork shares. The rule is written in `config/experiment.toml` under
`[cues.fix_rate]` and was fixed before this run.

**Frozen definition: `14d/drop/matched-hours`, cut 1.0.** It keeps 73% of true alerts (target 50%) and passes 65% of false alerts: ratio 1.119.

## Alerts used

| Group | True | False |
|---|---|---|
| vultures | 5 | 319 |
| storks | 80 | 1161 |

## Every variant at its operating cut

The lowest cut keeping the target share of true alerts; blank if none does.

| Variant | Cut | True passing | False passing | Ratio |
|---|---|---|---|---|
| 7d/count/all-hours | - | - | - | - |
| 7d/count/matched-hours | - | - | - | - |
| 7d/drop/all-hours | - | - | - | - |
| 7d/drop/matched-hours | 1.0 | 75% | 70% | 1.063 |
| 14d/count/all-hours | - | - | - | - |
| 14d/count/matched-hours | - | - | - | - |
| 14d/drop/all-hours | - | - | - | - |
| 14d/drop/matched-hours | 1.0 | 73% | 65% | 1.119 |

## Chosen variant by group and cut

| Cut | Group | True passing | False passing | Undefined (true / false) |
|---|---|---|---|---|
| 0.1 | vultures | 0/5 | 4/316 | 0 / 3 |
| 0.1 | storks | 0/72 | 11/995 | 8 / 166 |
| 0.2 | vultures | 0/5 | 9/316 | 0 / 3 |
| 0.2 | storks | 1/72 | 23/995 | 8 / 166 |
| 0.3 | vultures | 1/5 | 22/316 | 0 / 3 |
| 0.3 | storks | 2/72 | 34/995 | 8 / 166 |
| 0.4 | vultures | 1/5 | 34/316 | 0 / 3 |
| 0.4 | storks | 3/72 | 49/995 | 8 / 166 |
| 0.5 | vultures | 1/5 | 46/316 | 0 / 3 |
| 0.5 | storks | 4/72 | 60/995 | 8 / 166 |
| 0.7 | vultures | 2/5 | 92/316 | 0 / 3 |
| 0.7 | storks | 5/72 | 103/995 | 8 / 166 |
| 1.0 | vultures | 4/5 | 204/316 | 0 / 3 |
| 1.0 | storks | 47/72 | 650/995 | 8 / 166 |

## True alerts under the chosen variant

| Group | Bird | Ratio |
|---|---|---|
| vultures | LET_TUVU_68355 | 0.28 |
| vultures | LEV_TUVU_68356 | 0.83 |
| vultures | LEP_TUVU_68354 | 0.75 |
| vultures | PMH_BLVU_68354 | 0.55 |
| vultures | ACT_TUVU_111943 | 1.75 |
| storks | 8854045884 | undefined |
| storks | 8854045489 | 1.35 |
| storks | 8854045739 | 1.00 |
| storks | 8854045730 | 0.95 |
| storks | 8854045918 | 7.00 |
| storks | 8854045556 | undefined |
| storks | 8854045566 | undefined |
| storks | 8854045762 | 1.00 |
| storks | 8854045839 | 0.99 |
| storks | 8854045615 | 1.00 |
| storks | 8854045785 | 1.00 |
| storks | 8854045633 | 1.00 |
| storks | 8854045927 | 1.25 |
| storks | 8854045804 | 1.05 |
| storks | 8854045754 | 1.00 |
| storks | 8854045481 | 1.00 |
| storks | 8854045558 | 0.81 |
| storks | 8854045563 | 1.00 |
| storks | 8854045743 | 1.00 |
| storks | 8854045553 | 1.00 |
| storks | 8854045636 | 1.02 |
| storks | 8854045843 | undefined |
| storks | 8854045613 | 1.00 |
| storks | 8854045608 | 1.11 |
| storks | 8854045845 | 1.02 |
| storks | 8854045667 | 1.00 |
| storks | 8854045548 | 2.25 |
| storks | 8854045796 | 1.00 |
| storks | 8854045662 | 1.00 |
| storks | 8854045538 | 1.06 |
| storks | 8854045646 | 1.00 |
| storks | 8854045938 | 1.00 |
| storks | 8854045780 | 1.00 |
| storks | 8854045591 | 1.00 |
| storks | 8854045732 | 1.00 |
| storks | 8854045535 | 1.00 |
| storks | 8854045589 | 1.05 |
| storks | 8854045532 | 0.48 |
| storks | 8854045541 | 1.00 |
| storks | 8854045777 | 1.00 |
| storks | 8854045858 | 0.95 |
| storks | 8854045640 | 1.00 |
| storks | 8854045814 | 1.02 |
| storks | 8854045545 | 1.05 |
| storks | 8854045894 | 1.00 |
| storks | 8854045542 | 1.18 |
| storks | 8854045834 | 1.02 |
| storks | 8854045655 | 1.26 |
| storks | 8854045499 | 0.93 |
| storks | 4055914954 | undefined |
| storks | 4055890020 | 1.01 |
| storks | 4058297857 | 1.00 |
| storks | 4058223114 | 0.80 |
| storks | 4058088974 | 1.00 |
| storks | 4058376326 | 1.40 |
| storks | 4058312515 | 1.00 |
| storks | 4055858082 | 1.02 |
| storks | 4058369358 | 1.00 |
| storks | 4055884087 | 1.34 |
| storks | 4057950847 | 0.16 |
| storks | 4058341332 | 0.36 |
| storks | 4058341332 | 0.66 |
| storks | 4057964536 | 0.90 |
| storks | 4057920733 | undefined |
| storks | 4058279447 | undefined |
| storks | 4057971865 | 1.00 |
| storks | 4058229540 | 1.04 |
| storks | 4057974736 | 1.00 |
| storks | 4058248128 | undefined |
| storks | 4058037995 | 1.00 |
| storks | 4058257293 | 0.23 |
| storks | 4003339708 | 1.06 |
| storks | 4003339706 | 1.00 |
| storks | 4003339693 | 1.00 |
| storks | 4003339701 | 1.00 |
| storks | 4055820684 | 1.00 |
| storks | 4003339716 | 1.00 |
| storks | 4055824520 | 1.00 |
| storks | 4055824520 | 1.00 |
| storks | 4003339721 | 1.02 |
