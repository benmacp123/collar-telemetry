# Assumptions and their sources

Every threshold the pipeline uses, with where it came from. Labels:

- **Observed**: measured on this project's tuning data (vulture
  deployments starting before 2013). The scoring set (2013 on) was not
  inspected while choosing values; it was scored once, on 2026-10-18,
  after the thresholds were frozen.
- **Literature**: taken from a cited source.
- **Provisional**: a reasoned starting point, still to be checked on the
  tuning set.

Code: `src/telemetry/species.py` (per-species settings) and
`src/telemetry/synthetic.py` (synthetic mortality events).

## Speed limits for the cleaner

The speed filter should drop only impossible fixes, so each limit is a top
speed, not a typical one. Implied speeds between fixes are averaged over
minutes or hours, which leaves a wide margin for real movement.

| Taxon | Limit | Basis | Label |
|---|---|---|---|
| Turkey vulture, black vulture | 30 m/s | Tag-recorded ground speed on the tuning set: 99.9th percentile 18-19 m/s, maximum 23 m/s (one black vulture reading of 65 m/s treated as a GPS error). California condor listed at 90 km/h (25 m/s) [4]. | Observed, literature |
| Black-backed jackal | 17 m/s | 58-60 km/h (16.2-16.7 m/s) [1, 6], compiled in [4]. | Literature |
| African savanna elephant | 11 m/s | 34-40 km/h listed [2, 4]; fastest measured elephant gait 6.8 m/s [5]. | Literature |

The allometric model of Hirt et al. [4] predicts 36 m/s for a 2 kg flier,
12 m/s for a 7.8 kg runner and 9.6 m/s for a 2,800 kg runner. The species
entries are preferred because the flying model is fitted mostly on
flapping fliers, and vultures mostly soar.

## Mortality detector

| Setting | Value | Basis | Label |
|---|---|---|---|
| Stationary box (all taxa) | 100 m corner to corner | Stationary GPS collar tests report median errors of 6-20 m [3, 7]. Dead vultures on the tuning set scatter around their final position with a median of 16 m and a 95th percentile of 59 m. Tuning-set sweep: 150 m and 200 m add false alarms (1.26 and 1.47 against 0.95 per animal-month at 24 h) and flag no extra carcass deaths. | Observed (sweep); splits some deaths into several incidents (see below) |
| Window, vultures | 36 h | Must outlast the 12-14 h overnight roost. Tuning-set sweep (`results/SWEEP.md`): false alarms 0.95 / 0.59 / 0.23 / 0.10 per animal-month at 24 / 36 / 48 / 72 h. Carcass deaths flagged by the 92.5 h mark: 4 of 6 up to 36 h; at 48 h one is flagged after the mark under satellite uploads. | Observed (sweep, 6 carcass deaths) |
| Window, jackal | 24 h | Jackals lie up through the day. This study's deaths show at most about 10 h stationary before the track stops. | Provisional |
| Window, elephant | 12 h | Wild elephants sleep about 2 h a day, mostly 02:00-06:00 [8], and rarely stay within 100 m for long. Collar makers' own mortality triggers default to 4-8 h of inactivity [9]. | Provisional, literature-informed |
| Reopen window | 48 h | A reopen cannot come sooner than the detector window after a resolve, so it must exceed the longest window (36 h) with slack. | Provisional |

**Finding: the 100 m box splits one death into several incidents.** On
synthetic carcasses using the observed scatter, 15% of deaths (hourly
fixes) and 42% (30-minute fixes) became more than one incident. Each death
also produced 1.4-2.0 false "moving again" messages, because two stray
fixes in a row break the box. A 150 m box cut that to 0-3%, and 200 m to
0%. A larger box also makes a resting animal look dead sooner, so the box
size is chosen with that trade-off on the tuning set, not here.

## Unusual-movement detector

The detector compares each animal with its own baseline. The floor only
stops an animal that barely moves from alerting on a short walk.

| Taxon | Floor (3 h span) | Basis | Label |
|---|---|---|---|
| Vultures | 10 km | Cover tens of kilometres a day on the wing. | Provisional |
| Black-backed jackal | 3 km | Hourly moves of up to 3 km and a mean of 14.6 km a day (VHF, Botswana) [10]. | Literature-informed |
| African savanna elephant | 3 km | | Provisional |

## Geofence detector

| Setting | Value | Basis | Label |
|---|---|---|---|
| Edge band | 100 m either side of the boundary | Several times typical GPS error (10-30 m, stationary collar tests [3, 7]); fixes in the band change nothing, so jitter along a fence line does not alert. | Provisional |
| Fixes to confirm | 2 in a row beyond the band, to open or to resolve | One stray fix should not raise or clear an alert. | Provisional |
| Boundaries | OpenStreetMap relations for Etosha (2982497) and Kruger (1752987) | Redistributable (ODbL), unlike WDPA. Kruger's relation excludes the unfenced private reserves to its west, so crossings there alert. | Observed (source choice) |
| Projection | Local equirectangular plane centred on each park | Accurate to a few per cent over a park; tested to within 10 m at 5 km. | - |

Not chosen on data: no geofence ground truth exists. On the elephants,
excursions last a median of 15 h and 17% are under 6 h, so jitter is not
what drives the alerts.

## Synthetic mortality events

The jackal and elephant tracks stop at or before death, so the mortality
detector is scored on synthetic carcasses injected into real tracks. Every
such event is labelled synthetic in results.

| Setting | Value | Basis | Label |
|---|---|---|---|
| Schedule | The real collar's own timestamps | Keeps duty cycles and fix intervals realistic. | - |
| Fix success | 0.7 | A collar on a carcass is often tilted or under the body. Tilt cuts fix success sharply: 20-fold from 60° to 30° antenna angle in one habitat [3], and performance falls below 90° from vertical [11]. | Provisional |
| Scatter | Lognormal, median 16 m, 95th percentile 59 m, uniform direction | Dead vultures on the tuning set (5 deployments, 337 fixes); consistent with [3, 7]. | Observed |
| Collar life after death | 7 days | Dead vultures whose collars keep reporting do so for 53-337 h. Most (12 of 17) stop within hours, which is the gap detector's case. | Provisional, observed range |
| Death time | Random fix time, at least 7 days after the first fix and 7 days before the last (seeded) | Gives the detectors a baseline and covers the carcass period. | - |

## Replay runner

Settings in `src/telemetry/replay.py` that shape every reported result.

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

## References

1. Christiansen P (2002) Locomotion in terrestrial mammals: the influence
   of body mass, limb length and bone proportions on speed. *Zool. J. Linn.
   Soc.* 136:685-714.
2. Garland T (1983) The relation between maximal running speed and body
   mass in terrestrial mammals. *J. Zool.* 199:157-170.
3. Belant JL (2009) Effects of antenna orientation and vegetation on
   global positioning system telemetry collar performance. *Northeast.
   Nat.* 16:577-584.
4. Hirt MR, Jetz W, Rall BC, Brose U (2017) A general scaling law reveals
   why the largest animals are not the fastest. *Nat. Ecol. Evol.*
   1:1116-1122, Supplementary Table 4 and species database.
   <https://doi.org/10.1038/s41559-017-0241-4>
5. Hutchinson JR, Famini D, Lair R, Kram R (2003) Are fast-moving elephants
   really running? *Nature* 422:493-494.
   <https://doi.org/10.1038/422493a>
6. Iriarte-Díaz J (2002) Differential scaling of locomotor performance in
   small and large terrestrial mammals. *J. Exp. Biol.* 205:2897-2908.
7. Adams AL, Dickinson KJM, Robertson BC, van Heezik Y (2013) An evaluation
   of the accuracy and performance of lightweight GPS collars in a
   suburban environment. *PLoS ONE* 8:e68496.
   <https://doi.org/10.1371/journal.pone.0068496>
8. Gravett N et al. (2017) Inactivity/sleep in two wild free-roaming
   African elephant matriarchs: does large body size make elephants the
   shortest mammalian sleepers? *PLoS ONE* 12:e0171903.
   <https://doi.org/10.1371/journal.pone.0171903>
9. Lotek Wireless, LifeCycle Pro Series specification sheet (default
   mortality delay 4 h); USDA Forest Service test of the Lotek GPS_2200
   (default 8 h). Manufacturer figures.
10. Kaunda SKK (2001) Spatial utilization by black-backed jackals in
    southeastern Botswana. *Afr. Zool.* 36:143-152.
11. D'Eon RG, Delparte D (2005) Effects of radio-collar position and
    orientation on GPS radio-collar performance, and the implications of
    PDOP in data screening. *J. Appl. Ecol.* 42:383-388.
    <https://doi.org/10.1111/j.1365-2664.2005.01010.x>
