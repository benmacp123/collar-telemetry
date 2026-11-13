# Stork acceleration cue: likelihood ratio at the watch alert

Written by `make acceleration` from the stork tuning populations only.
The cue is the median of the hourly `spread_median` over the 24 hours before a watch alert opened (at least 12 of them held), and passes when it is at or below the threshold. The definition is in `config/experiment.toml`.

Watch alerts: 80 true and 1161 false (on 164 birds). Without a cue value: 14 true, 323 false; they are left out of the shares below.

| Threshold | True alerts passing | False alerts passing | Likelihood ratio | Conservative lower bound |
|---:|---:|---:|---:|---:|
| 1 | 12/66 (18.2%) | 3/838 (0.4%) | 50.787 | 10.235 |
| 1.5 | 13/66 (19.7%) | 3/838 (0.4%) | 55.02 | 11.353 |
| 2 | 14/66 (21.2%) | 3/838 (0.4%) | 59.252 | 12.488 |
| 2.5 | 14/66 (21.2%) | 5/838 (0.6%) | 35.549 | 9.415 |
| 3 | 14/66 (21.2%) | 8/838 (1.0%) | 22.219 | 6.985 |
| 4 | 14/66 (21.2%) | 16/838 (1.9%) | 11.11 | 4.248 |
| 5 | 14/66 (21.2%) | 30/838 (3.6%) | 5.925 | 2.582 |
| 6 | 16/66 (24.2%) | 45/838 (5.4%) | 4.514 | 2.181 |
| 8 | 28/66 (42.4%) | 100/838 (11.9%) | 3.555 | 2.184 |
| 10 | 50/66 (75.8%) | 207/838 (24.7%) | 3.067 | 2.315 |
| 12 | 54/66 (81.8%) | 348/838 (41.5%) | 1.97 | 1.578 |
| 15 | 58/66 (87.9%) | 518/838 (61.8%) | 1.422 | 1.197 |
| 20 | 62/66 (93.9%) | 676/838 (80.7%) | 1.165 | 1.027 |
| 30 | 64/66 (97.0%) | 784/838 (93.6%) | 1.036 | 0.943 |

## Operating point

The frozen rule takes the lowest threshold keeping at least 50.0% of the true alerts: **10**.
There 75.8% of true and 24.7% of false alerts pass, a ratio of **3.067** (conservative lower bound 2.315).

The conservative bound divides the true share's Wilson lower bound by the false share's Wilson upper bound. Both treat alerts as independent, but false alerts cluster on few birds, so the real uncertainty is wider.

## What it would mean for precision

Tuning population: 2854 animal-months, 1161 false watch alerts (0.407 per animal-month).
After the cue: 207 false alerts remain (0.073 per animal-month). Precision among alerts with a cue value is 19.5%, Wilson 95% interval [0.150801, 0.247301]; the escalated target needs a lower bound above 15%.
