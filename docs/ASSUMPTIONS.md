# Assumptions and their sources

Every setting the pipeline and its evaluation use, with where it came
from. Labels:

- **Observed**: measured on this project's tuning data (vulture
  deployments starting before 2013). The scoring set (2013 on) was not
  inspected while choosing values; it was scored on 2026-10-18, after
  the thresholds were frozen, and its figures are recomputed on every
  run. Later looks at it are declared in the README's limitations.
- **Literature**: taken from a cited source.
- **Provisional**: a reasoned starting point, still to be checked on the
  tuning set.
- **-**: a design or method choice (a definition, a seed, a structure),
  not an estimate of anything, so there is nothing to observe or cite.

Code: `src/telemetry/core/species.py` (per-species settings) and
`src/telemetry/sim/synthetic.py` (synthetic mortality events).

## Speed limits for the cleaner

The speed filter should drop only impossible fixes, so each limit is a top
speed, not a typical one. Implied speeds between fixes are averaged over
minutes or hours, which leaves a wide margin for real movement.

| Taxon | Limit | Basis | Label |
|---|---|---|---|
| Turkey vulture, black vulture | 30 m/s | Tag-recorded ground speed on the tuning set: 99.9th percentile 18-19 m/s, maximum 23 m/s (one black vulture reading of 65 m/s treated as a GPS error). California condor listed at 90 km/h (25 m/s) in [4], whose source for it is a website (speedofanimals.com), so it is supporting only. | Observed |
| Black-backed jackal | 17 m/s | 59.98 km/h from [1] and 58.29 km/h from [6] (16.2-16.7 m/s), as listed in [4]'s speed database; the primary papers were not read. | Literature (secondary) |
| African savanna elephant | 11 m/s | 35 km/h from [2], as listed in [4] (which also lists 34 and 40 km/h from other sources); the fastest gait measured, on 42 Asian elephants, was about 15 mph (6.7 m/s) [5]. | Literature (secondary) |

The speed filter subtracts twice `gps_error_m` (30 m) from each step
before comparing it with the limit, so on the 1-3 min tags GPS jitter
cannot trip it: at a 1-minute interval a fix would need to be about 900 m
off. Short intervals do bring implied speeds closer to instantaneous ones,
which is why the vulture limit is set against the tuning set's
instantaneous tag speeds (maximum 23 m/s) rather than hourly averages.

The allometric model of Hirt et al. [4] (Supplementary Table 4) predicts
36 m/s for a 2 kg flier, 12 m/s for a 7.8 kg runner and 9.6 m/s for a
2,800 kg runner. The species entries are preferred for vultures because
the flying model is fitted on 55 data points (29 birds), several of them
raptor stoop speeds (red-tailed hawk 195 km/h), and vultures soar rather
than stoop.

Other cleaner settings (`src/telemetry/core/cleaning.py`; the hold is set
per arrival scenario in `src/telemetry/sim/arrival.py`):

| Setting | Value | Basis | Label |
|---|---|---|---|
| GPS error allowance | 30 m per fix | Upper end of stationary collar tests: median 5.8 m (open area, [3]) and 16.9 m (open sky, [7]), about 30 m on average under suburban cover [7]. | Provisional, literature-informed |
| Rejections before a new anchor | 3 in a row | If the fix every later one is judged against was itself wrong, the speed filter would otherwise drop the rest of the track; after three rejections the next fix is taken as the new anchor. | Provisional |
| Reorder hold | 0 (ideal, satellite), 3 h (GSM) | Satellite delivery is taken as in order. Under GSM a fix retried k times arrives k uploads late with probability 0.05^k, so 3 h reorders nearly every retry; a longer hold would delay every alert by as much. Backlog fixes more than 3 h late are dropped and counted (about 1% under GSM). | Provisional |

## Mortality detector

| Setting | Value | Basis | Label |
|---|---|---|---|
| Stationary box (all taxa) | 100 m corner to corner | Stationary GPS collar tests report median errors of 5.8 m (open area, [3]) and 16.9 m (open sky, [7]), and about 30 m on average under suburban cover [7]. Dead vultures on the tuning set scatter around their final position with a median of 15.9 m and a 95th percentile of 36.5 m, leaving out repeated positions (`make carcass`). Tuning-set sweep: 150 m and 200 m add false alarms (1.26 and 1.47 against 0.95 per animal-month at 24 h) and flag no extra carcass deaths. | Observed (sweep) |
| Window, vultures | 36 h | Must outlast the 12-14 h overnight roost. Tuning-set sweep (`results/sweep/SWEEP.md`): false alarms 0.95 / 0.59 / 0.23 / 0.10 per animal-month at 24 / 36 / 48 / 72 h. Carcass deaths flagged by the 92.5 h mark: 4 of 6 up to 36 h; at 48 h one is flagged after the mark under satellite uploads. | Observed (sweep, 6 carcass deaths) |
| Window, jackal | 24 h | Jackals lie up through the day and travel a mean of 14.6 km a day [10]. No published lie-up durations for black-backed jackals were found. This study's deaths show at most about 10 h stationary before the track stops (seen while labelling, not used to choose the value). Not checked: whether jackals feeding at large carcasses (the Etosha study's subject) stay within 100 m for a day. | Provisional |
| Window, elephant | 12 h | Wild elephants sleep about 2 h a day, mostly 02:00-06:00, with no single bout over 142 min [8]. On this Kruger population, continuous stays at water average 2.6 h (wet season) and 3.5 h (dry, s.d. 4.1 h), measured within 200 m of water [12], so a long dry-season stay at water is the most likely false alarm. Collar makers' activity-sensor mortality timers default to 4-24 h [9]; those measure collar motion, not position. | Provisional, literature-informed |
| Minimum fixes in the cluster | 6 | Two fixes a day apart are not enough evidence of a carcass. Tuning-set probe (2026-10-22): 5 or 3 flags one more sparse carcass (MEM_BLVU_68361), but only after the 92.5 h mark, for 0.01-0.05 more false alerts per animal-month; the other missed one (LXE_TUVU_68359, still for 25 h) is shorter than the window, so no value catches it. | Provisional, checked on tuning data |
| Leaving radius, once alerted (all taxa) | 75 m from the cluster's centre at the alert | The growing box lets scattered carcass fixes read as "moving again" (see below). Smallest radius with no flaps on the tuning-seed synthetic deaths of either mammal (50 m leaves 1 and 3); applies only after an alert, so it changes no open or detection. Twice the carcass scatter's 95th percentile (36.5 m). Cost on the vulture tuning set: false alerts stay open a median 8 h (7 h with the box) and a 90th percentile 89 h (75 h). Chosen by the owner, 2026-10-22. | Observed (tuning data, `make departure`) |
| Leave fixes | 2 in a row | Three cut flaps less than the radius and add false alerts (0.86 against 0.59 per animal-month on the vulture tuning set), and lose one carcass death by the mark under satellite uploads. | Observed (tuning data, `make departure`) |
| Reopen window | 48 h | A reopen cannot come sooner than the detector window after a resolve, so it must exceed the longest window (36 h) with slack. 72 h and 96 h change no death outcome with the box and keep merged false alerts open longer. | Provisional; checked on tuning data |
| Potential death | Raised while a mortality and a gap incident are open together; resolves and reopens with mortality | No parameter of its own. A "silent while still" variant (gap on a collar still for 14 h or more) was tried and rejected: it caught both sparse carcass tails but cut precision on both vulture sets (see the README's limitations). | - |

**Finding: the growing box makes carcasses "move again".** The box
stretches with every fix, so a carcass reporting hundreds of scattered
fixes sooner or later puts two in a row past its far edge, and the alert
resolves as "moving again" while the animal is still dead. Measured with
`make departure` on tuning data only: the vulture tuning set and mammal
variants drawn with seed 2027, not the reported variants' seed 2026.
With the box alone, 10 of 22 jackal and 11 of 14 elephant deaths in the
reporting regime flapped (16 and 23 flaps in all). The 48 h reopen window
merged every flap, so no death split into two incidents, but the operator
saw each one as a resolve and a reopen (no second email, since the
notifier sends once per incident). A 150 m box cut flaps to 1 each but added
about a third more false alerts on living vultures; the 75 m leaving radius cut
them to 0 with no new false alert. The one vulture carcass that flaps
under every setting (PMH_BLVU_68354) really moved: it lay still from
14 May 2011, shifted 247 m on 20 May and died there, and the reopen joins
the two stays. An earlier measurement (15-42% of deaths split, from a
scatter of 16 / 59 m that did not reproduce) is superseded.

## Data-gap detector

The two settings that depend on the upload plan, `allowance` and
`min_silence`, are under the replay runner below. The rest
(`src/telemetry/core/detectors/gap.py`) shape how the detector learns a
collar's schedule:

| Setting | Value | Basis | Label |
|---|---|---|---|
| Warm-up | 3 days from the first fix | Long enough to see a daily duty cycle a few times before alerting on it. | Provisional |
| Schedule memory | Half-life 14 days | Follows a schedule change within weeks while one quiet day barely moves it. | Provisional |
| Active hour | At least 25% of the busiest hour's weight | Keeps hours the collar is only occasionally on from counting as hours it should be heard in. | Provisional |
| Usual interval | Median of the last 50 intervals | A median ignores the overnight gap on duty-cycled tags; 50 covers about two days of hourly fixes. | Provisional |

## Unusual-movement detector

The detector compares each animal with its own baseline. The floor only
stops an animal that barely moves from alerting on a short walk.

| Taxon | Floor (3 h span) | Basis | Label |
|---|---|---|---|
| Vultures | 10 km | Cover tens of kilometres a day on the wing. On the tuning set the bird's own threshold (2 x its 99th percentile) is above 10 km for 32 of 34 birds (median 33 km), so the floor is a backstop; it binds for two black vultures (7.7 and 9.3 km). | Provisional, checked on the tuning set |
| Black-backed jackal | 3 km | 3 km in 3 h is about 1.7 times the mean daily rate of 14.6 km a day (VHF, Botswana) [10]. | Provisional, literature-informed |
| African savanna elephant | 3 km | 3 km in 3 h is about 2.5 times the mean speed of this Kruger population (0.4 km/h, 30-min fixes) and twice the fastest water-to-water segment average (1.5 km/h) [12]. | Provisional, literature-informed |

Settings shared by every taxon (`src/telemetry/core/detectors/movement.py`):

| Setting | Value | Basis | Label |
|---|---|---|---|
| Span | 3 h of net displacement | A fixed span makes hourly and 1-minute tags comparable, and net distance stops GPS jitter on fast tags adding up. | Provisional |
| Coverage | Fixes must cover 75% of the span | Distance across a gap is not speed. | Provisional |
| Threshold | 2 x the animal's own 99th percentile | Far enough outside the animal's normal that daily variation does not reach it. | Provisional |
| Warm-up | 7 days and 50 measurements | Enough of the animal's own movement for a 99th percentile to mean something. | Provisional |
| Baseline memory | Half-life 14 days | Follows seasonal change in range use. | Provisional |
| Longest episode | 24 h | Measurements during an alert do not teach the baseline, so a lasting change (a relocation) must not keep it open and blind for good. | Provisional |

## Geofence detector

| Setting | Value | Basis | Label |
|---|---|---|---|
| Edge band | 100 m either side of the boundary | Several times typical GPS error (6-30 m, stationary collar tests [3, 7]); fixes in the band change nothing, so jitter along a fence line does not alert. | Provisional |
| Fixes to confirm | 2 in a row beyond the band, to open or to resolve | One stray fix should not raise or clear an alert. | Provisional |
| Boundaries | OpenStreetMap relations for Etosha (2982497) and Kruger (1752987) | Redistributable (ODbL), unlike WDPA. Kruger's relation excludes the unfenced private reserves to its west, so crossings there alert. | - (source choice) |
| Projection | Local equirectangular plane centred on each park | Accurate to a few per cent over a park; tested to within 10 m at 5 km. | - |

Not chosen on data: no geofence ground truth exists. On the elephants,
excursions last a median of 15 h and 17% are under 6 h, so jitter is not
what drives the alerts.

## Synthetic mortality events

The jackal and elephant tracks stop at or before death, so the mortality
detector is scored on synthetic carcasses injected into real tracks. Every
such event is labelled synthetic in results. Measured values come from
`make carcass` (`results/carcass/carcass.json`): the 6 carcass deaths in
the vulture tuning set, and checks on every study's collars. A test holds
the defaults in `src/telemetry/sim/synthetic.py` to that file.

| Setting | Value | Basis | Label |
|---|---|---|---|
| Schedule | The real collar's own timestamps | Keeps duty cycles and fix intervals realistic. | - |
| Fix success | Two regimes, drawn per carcass: half *reporting* (0.54 of the collar's recorded fixes kept), half *sparse* (0.14) | Dead vultures' rate of new positions on the carcass against their own rate in the 14 days before: 0.43, 0.54 and 0.73 for three, 0.08, 0.14 and 0.15 for the other three, none between (cut at 0.3). The sparse three include both carcass deaths the mortality detector misses. A single rate (0.7 before this review) never produces sparse tails. Tilt and a body over the collar explain the loss: fix success falls 20-fold from 60° to 30° antenna angle in alder [3], and is significantly lower below 90° from vertical [11]. Applied to the real collar's recorded fixes, so it is a ratio to the live rate. | Observed (n = 6) |
| Repeated positions | Not counted as fixes | About half of the reporting vultures' carcass fixes repeat the previous fix's exact coordinates (72 of 164, 46 of 71), against a median of 10% over whole vulture tracks: the tags resend a position. Counting them would put the reporting ratio at 0.95 and the scatter median at 0 m. The mammal collars rarely do it (elephants 0%, jackals median 4%), so synthetic carcasses have none. | Observed |
| Scatter | Lognormal, median 15.9 m, 95th percentile 36.5 m, uniform direction | Dead vultures' distances from their carcass's median position, repeated positions left out (156 fixes). Consistent with stationary collar tests (median 5.8 m [3], 16.9 m [7]) and with the elephant collars' stillest 6-fix windows (median 11 m across collars, an upper bound since a resting elephant still shifts). The jackal collars' stillest windows give about 2 m, too tight to take as GPS error, so they are not used. The earlier figures (median 16 m, 95th percentile 59 m, labelled observed) did not reproduce from any committed code. | Observed (vultures), checked on elephants |
| Collar life after death | Reporting: 30 days; sparse: 25, 88 or 97 h, drawn per carcass; either way, at most until the real track ends | The sparse lives are the three observed sparse tails (`make carcass`): the real sparse carcasses the mortality detector misses stopped early too, while a 30-day sparse tail eventually gives it enough fixes. Chosen by the owner, 2026-10-22. The vulture tags are solar powered (Microwave Telemetry), and most (12 of 17 dead) stop within hours, plausibly with the panel under the body; those whose tags keep going report for 53-337 h. The mammal collars (African Wildlife Tracking) are assumed battery powered and to keep reporting; not confirmed for these collars. Detection comes within a day or two, so the value mainly decides whether the collar falls silent within the replay's watch, which drives the gap and `potential_death` alerts on synthetic deaths. | Observed (sparse, n = 3); provisional (reporting) |
| Death time | Random fix time, at least 7 days after the first fix and 7 days before the last, with the real collar recording through those 7 days (no gap over 24 h) (seeded) | Gives the detectors a baseline and a carcass period with fixes in it; without the coverage rule a death just before a long outage (230 days on one elephant collar) would be a silent collar, not a carcass. | - |
| Deaths per deployment | Two, at the same time: one reporting carcass, one sparse (seed 2026, per deployment) | Gives per-regime results on the same tracks, with no sampling noise in the regime mix; pooled results are 50/50, matching the observed share. The two copies share their pre-death track, so they are not independent deaths. Built as separate variants (`jackals-synthetic`, `elephants-synthetic`; `src/telemetry/analysis/variants.py`), scored on deaths only; load stays with the real studies. Chosen by the owner. | - |
| Synthetic death start | Computed from the fixes as for real deaths; also scored from the injected time | Keeps one definition across studies. One lognormal scatter fix beyond the 100 m radius moves the computed start after it (5 of 72 deaths, 25-636 h later), so both delays are reported. | - |
| Dropped collar | No separate case | A collar that falls off lies still like a reporting carcass; one cut off and destroyed goes silent, which the gap detector handles. | - |

## Replay runner

Settings in `src/telemetry/sim/replay.py` (tick, watch, seed) and
`src/telemetry/core/pipeline.py` (gap allowance) that shape every reported
result.

| Setting | Value | Basis | Label |
|---|---|---|---|
| Clock tick | 1 h | Gap alerts can be raised up to one tick late; fine against thresholds of 6 h or more. | Provisional |
| Gap `allowance` (clock time) | Upload interval + 36 h (36 h ideal, 37 h GSM, 60 h daily, 84 h every other day) | The newest fix can be a whole upload interval old when it arrives; upload delay runs on the clock, so it is not counted in active hours. Tuning-set sweep, ideal arrival: margins of 6 / 12 / 24 / 36 / 48 h give 2.89 / 2.54 / 1.08 / 0.88 / 0.50 gap alerts per animal-month for a median delay of 14 / 14 / 24 / 36 / 48 h on deaths; 36 h also cuts GSM to 1.11 (3.36 at 24 h), since it absorbs whole out-of-coverage days. Every tuning-set death is flagged at every margin. Chosen on vultures and applied to the mammals unchanged. | Observed (sweep) |
| Gap `min_silence` (active hours) | 6 h, or 3x the usual fix interval if longer | Also required: silence through the collar's normal hours, so a nightly switch-off is not a gap. | Provisional |
| Planned ends | `removal`, `captured`, `released`: ticking stops at deploy-off | The operator knows about these when they happen (Movebank end-type definitions). | Provisional |
| Other ends | Watched for 7 days after the last arrival | Deaths, transmission ends and unknown ends are only known afterwards, so the final silence can raise a gap alert. | Provisional |
| Arrival seed | 2026 | Fixed so every run gives the same results. | - |

Fixed before scoring (2026-10-18): the upload allowance used to be
counted in the collar's active hours, and active hours were weighted by
fix count, so a 1-min burst tag on for about 5 hours a day needed well
over a week of real silence to alert, past the 7-day watch. The allowance
now runs on the clock and each clock hour with a fix counts once. The
earlier 24 h margin was chosen under the old rule, where it behaved like
about 30 h of clock time on the hourly tuning tags; 36 h is the closest
match under the new rule.

## Arrival scenarios

Upload patterns in `src/telemetry/sim/arrival.py`. They resemble vendor
upload plans (Telonics and Telemetry Solutions GPS/Iridium
specifications: daily or every-other-day uplinks, many fixes per
message) but are not measured on any collar, so every result is reported
under all four rather than tuned to one.

| Setting | Value | Basis | Label |
|---|---|---|---|
| Ideal | Every fix arrives when taken | Baseline with no transmission effects. | - |
| Satellite uploads | Once a day, or every other day, from a random phase per collar; reliable and in order | The two common uplink tiers. | Provisional |
| GSM upload interval | Hourly while in coverage | Phone-network collars send as soon as they can. | Provisional |
| GSM out-of-coverage days | 10% of UTC days | An assumed share, for animals ranging beyond mast coverage; not measured. | Provisional |
| GSM failed sends | 5% of attempts, retried at the next upload | Puts fixes out of order, which the cleaner must handle. | Provisional |
| GSM duplicates | 1% of fixes sent again | As when the collar misses an acknowledgement. | Provisional |

## Evaluation definitions

How deaths are timed and scored (`src/telemetry/analysis/evaluation.py`).
These are fixed before scoring and never move with a detector setting, so
a threshold change cannot change what it is scored against.

| Setting | Value | Basis | Label |
|---|---|---|---|
| Death start radius | 100 m from the median of the last 5 fixes | Dead vultures' fixes scatter a median 15.9 m and a 95th percentile 36.5 m around their carcass (`make carcass`); the median of 5 resists one scattered last fix. | Observed |
| Sensitivity radius | 200 m | Reported beside 100 m to show how much the death start matters. | - |
| Carcass minimum | 24 h (vultures, jackals), 12 h (elephants) | The mortality windows in force before the threshold sweep, frozen so labels, the carcass/gap split and the mark stay put while the detector's window is tuned. | - |
| Reference mark, vultures | 92.5 h | Median time tuning-set carcass collars kept reporting, so half are silent by then. | Observed (n = 6) |
| Reference mark, mammals | Carcass minimum + 68.5 h (92.5 h jackals, 80.5 h elephants) | No mammal carcass periods exist, so the vulture mark's time after the vulture carcass minimum is carried over. | Provisional |
| Tuning / scoring split | Vulture deployments before / from 2013 | Separates hourly tags (tuning) from mostly 1-3 min tags (scoring), so scoring also tests whether thresholds carry across fix rates. | - |
| Animal-month | 30.4375 days of track | A mean calendar month. | - |

## References

Checked 2026-10-22. Each entry says how far it was checked: full text,
abstract, a secondary listing, or not reachable. A figure taken from a
source that could not be read in full says so in the tables above.

1. Christiansen P (2002) Locomotion in terrestrial mammals: the influence
   of body mass, limb length and bone proportions on speed. *Zool. J. Linn.
   Soc.* 136:685-714. Not read; value as listed in [4].
2. Garland T (1983) The relation between maximal running speed and body
   mass in terrestrial mammals. *J. Zool.* 199:157-170. Not read; value
   as listed in [4].
3. Belant JL (2009) Effects of antenna orientation and vegetation on
   global positioning system telemetry collar performance. *Northeast.
   Nat.* 16:577-584. Results checked (publisher's page).
4. Hirt MR, Jetz W, Rall BC, Brose U (2017) A general scaling law reveals
   why the largest animals are not the fastest. *Nat. Ecol. Evol.*
   1:1116-1122. Supplementary Information checked: Supplementary Table 4
   (model fits) and the maximum speed database.
   <https://doi.org/10.1038/s41559-017-0241-4>
5. Hutchinson JR, Famini D, Lair R, Kram R (2003) Are fast-moving elephants
   really running? *Nature* 422:493-494.
   <https://doi.org/10.1038/422493a> Paper not reachable; speed and
   sample from the University of Colorado press release (1 April 2003).
6. Iriarte-Díaz J (2002) Differential scaling of locomotor performance in
   small and large terrestrial mammals. *J. Exp. Biol.* 205:2897-2908.
   Abstract checked; value as listed in [4].
7. Adams AL, Dickinson KJM, Robertson BC, van Heezik Y (2013) An evaluation
   of the accuracy and performance of lightweight GPS collars in a
   suburban environment. *PLoS ONE* 8:e68496.
   <https://doi.org/10.1371/journal.pone.0068496> Full text checked.
8. Gravett N et al. (2017) Inactivity/sleep in two wild free-roaming
   African elephant matriarchs: does large body size make elephants the
   shortest mammalian sleepers? *PLoS ONE* 12:e0171903.
   <https://doi.org/10.1371/journal.pone.0171903> Full text checked.
9. Collar makers' activity-sensor mortality delays, manufacturer figures:
   Lotek LifeCycle Pro 330/500 product page, default 24 h (checked
   2026-10-22); Lotek LifeCycle Pro Series specification sheet (May 2024),
   default 4 h (no longer online; seen in a search listing only); USDA
   Forest Service evaluation of the Lotek GPS_2200, default 8 h (page not
   reachable; seen in a search listing only).
10. Kaunda SKK (2001) Spatial utilization by black-backed jackals in
    southeastern Botswana. *Afr. Zool.* 36:143-152.
    <https://doi.org/10.1080/15627020.2001.11657132> Abstract checked.
11. D'Eon RG, Delparte D (2005) Effects of radio-collar position and
    orientation on GPS radio-collar performance, and the implications of
    PDOP in data screening. *J. Appl. Ecol.* 42:383-388.
    <https://doi.org/10.1111/j.1365-2664.2005.01010.x> Abstract checked.
12. Thaker M, Gupte PR, Prins HHT, Slotow R, Vanak AT (2019) Fine-scale
    tracking of ambient temperature and movement reveals shuttling
    behavior of elephants to water. *Front. Ecol. Evol.* 7:4.
    <https://doi.org/10.3389/fevo.2019.00004> Full text checked. The
    paper behind this project's elephant data, so its figures describe
    the same animals; they are published values, not this project's
    results.
