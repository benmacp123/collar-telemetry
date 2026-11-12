# Data sources

One entry per dataset: name, URL, DOI, licence, date retrieved, and what
was extracted. Tracking data is CC0 or CC-BY only; the park boundaries are
an OpenStreetMap extract under the ODbL (see the last section).

## Black-backed jackal, Etosha National Park, Namibia

- **Data package:** Bellan SE, Getz WM (2017) Data from: Resource-driven
  encounters and the induction of disease among consumers. Movebank Data
  Repository. <https://doi.org/10.5441/001/1.n1r7ds5r>
- **Landing page:** <https://datarepository.movebank.org/handle/10255/move.706>
- **Movebank study:** "Black-backed jackal, Etosha National Park, Namibia"
  (study ID 304875150)
- **Licence:** CC0 1.0 Universal
- **Retrieved:** 2026-10-16
- **Files (unmodified, as downloaded):**
  - `raw/Black-backed jackal, Etosha National Park, Namibia.csv` - GPS
    fixes (130,688 rows, 22 deployments on 20 animals, 2009-2011)
  - `raw/Black-backed jackal, Etosha National Park, Namibia-reference-data.csv`
    - one row per deployment, including `deployment-end-type`
  - `raw/carcassLocations.csv` - anthrax carcass locations and jackal
    counts at carcasses
  - `raw/JACKALS.md` - the package README (published as `README.txt`)
- **Related publications:**
  - Borchering RK et al. (2017) J. R. Soc. Interface.
    <https://doi.org/10.1098/rsif.2017.0555>
  - Bellan SE et al. (2012) J. Wildl. Dis. 48(2):371-381.
    <https://doi.org/10.7589/0090-3558-48.2.371>
  - Abrahms B et al. (2017) Movement Ecology 5:12.
    <https://doi.org/10.1186/s40462-017-0104-2>

## African elephant, Kruger National Park

- **Data package:** Slotow R, Thaker M, Vanak AT (2019) Data from:
  Fine-scale tracking of ambient temperature and movement reveals shuttling
  behavior of elephants to water. Movebank Data Repository.
  <https://doi.org/10.5441/001/1.403h24q5>
- **Landing page:** <https://datarepository.movebank.org/handle/10255/move.980>
- **Movebank study:** "ThermochronTracking Elephants Kruger 2007"
  (study ID 736029750)
- **Licence:** CC0 1.0 Universal
- **Retrieved:** 2026-10-16
- **Files (unmodified, as downloaded):**
  - `raw/ThermochronTracking Elephants Kruger 2007.csv` - GPS fixes with
    collar temperature (283,688 rows, 14 adult females, 2007-2009)
  - `raw/ThermochronTracking Elephants Kruger 2007-reference-data.csv` -
    one row per deployment (downloaded as `...-reference-data(1).csv`;
    renamed only)
  - `raw/ELEPHANTS.md` - the package README
- **Related publication:** Thaker M, Gupte PR, Prins HHT, Slotow R, Vanak AT
  (2019) Front. Ecol. Evol. 7:4.
  <https://doi.org/10.3389/fevo.2019.00004>
- **Note:** the three `dead` deployments record deaths after the tracking
  data ends (August 2009), so the tracks contain no mortality events.

## Vultures, southeastern United States

- **Data package:** Kluever BM (2026) Data from: Study "Vultures tagged in
  the southeastern United States" [part]. Movebank Data Repository.
  <https://doi.org/10.5441/001/1.666>
- **Movebank study:** "Vultures tagged in the southeastern United States"
  (study ID 24797204)
- **Licence:** CC0 1.0 Universal
- **Retrieved:** 2026-10-18
- **Files:**
  - `raw/Vultures tagged in the southeastern United States_part-gps-1.csv`
    to `-6.csv` - GPS fixes (1,316,403 rows, 57 deployments on black and
    turkey vultures, 2006-2021). The published
    `..._part-gps.csv` is 249 MB, over GitHub's 100 MB file limit, so it
    is committed split by `scripts/split_events.py`: each part has the
    original header and rows byte for byte in their original order, and
    each animal's rows sit in a single part. The split was checked to
    reproduce the original rows exactly.
  - `raw/Vultures tagged in the southeastern United States_part-reference-data.csv`
    - one row per deployment, including `deployment-end-type`, mortality
    type and death comments (unmodified)
  - `raw/VULTURES.md` - the package README
- **Related publication:** Evans BA, Humphrey JS, Tillman EA, Avery ML,
  Kluever BM (2024) Site-specific space use and resource selection by black
  vultures (*Coragyps atratus*) in the southeastern USA. Ibis 166(1):129-145.
  <https://doi.org/10.1111/ibi.13244>
- **Note:** 21 deployments end `dead` and 4 `dead/fall-off`, most with a
  recorded cause. Several of these tracks end in multi-day stationary
  periods, so this is the only committed study with mortality events
  inside the tracks.

### Second-sensor check (2026-10-30)

Checked whether any sensor besides GPS that measures the animal's state
(activity, acceleration, temperature, mortality flag) is available for
these deployments, through the repository's public DSpace API
(`/server/api/pid/find?id=hdl:10255/move.3482`) and DataCite
(`api.datacite.org/dois/10.5441/001/1.666`).

| Source | Sensor types | Licence |
| --- | --- | --- |
| Published package (handle 10255/move.3482) | `gps` only; every row of all six committed parts has sensor type `gps`. Its extra columns (HDOP, VDOP, satellite count, ground speed, heading, height) describe fix quality, not the animal. | CC0 1.0 |
| Live Movebank study 24797204 | `gps` and `accessory-measurements`, the latter with `external_temperature`, `mw_activity_count` and `tag_battery_voltage` (Movebank API with a personal login: `study` and `study_attribute` entities). The live study is larger than the package: 60 deployments and about 3.0 million locations, to 2026-08. | `CUSTOM` licence; a personal account cannot view or download the data (`i_can_see_data` and `i_have_download_access` both false) |

No other repository package comes from study 24797204 (DataCite search on
the study name, 2026-10-30). So the study does record a body-state sensor
(activity count and tag temperature), but only the GPS part is published
under CC0. The rest needs the data owner's permission and a licence that
allows redistribution before it can be used here.

## Candidate: Vultures Acopian Center USA GPS (not committed)

- **Data package:** Bildstein KL, Barber D, Bechard MJ, Graña Grilli M,
  Therrien J (2021) Data from: Study "Vultures Acopian Center USA GPS"
  (2003-2021). Movebank Data Repository.
  <https://doi.org/10.5441/001/1.f3qt46r2>
- **Landing page:** <https://datarepository.movebank.org/handle/10255/move.1306>
- **Movebank study:** "Vultures Acopian Center USA GPS" (study ID 481458)
- **Licence:** CC BY 4.0 on the repository item (`dc.rights`); DataCite
  lists the file DOIs as CC0. CC BY is the stricter of the two, so it governs and
  needs the citation above.
- **Checked:** 2026-10-30 (file list, the first 4 KB of the accessory file,
  the reference data and the README; nothing committed).
- **Sensor types:** `gps` (`..._2003-2021-gps.csv`, 309 MB) and
  `accessory-measurements` (`..._2003-2021-accessory.csv`, 109 MB): tag
  external temperature, activity count (`gt:activity-count` for GeoTrak
  tags, `mw:activity-count` for Microwave Telemetry tags), tag voltage and
  battery voltage. The README quotes the Microwave Telemetry PTT-100
  manual: a constant activity counter over two or more transmission
  periods, with unvarying locations, suggests a detached tag or a bird
  that is down.
- **Deployments:** 85 (73 turkey, 12 black vultures). 5 end `dead`; about
  10 have comments that describe a death, not yet labelled. One of these
  ("Mandeb") died years after its tag failed, so it is not a death inside
  the track. No tag ID is shared with study 24797204.

## Candidate: LifeTrack White Stork SW Germany (not committed)

- **Data package:** Data from: Study "LifeTrack White Stork SW Germany"
  (2013-2023). Movebank Data Repository.
  <https://doi.org/10.5441/001/1.ck04mn78_2>
- **Landing page:** <https://datarepository.movebank.org/handle/10255/move.1685>
- **Movebank study:** "LifeTrack White Stork SW Germany" (study ID 21231406)
- **Licence:** CC0 1.0 on the repository item; the live study is CC BY.
- **Checked:** 2026-10-30 (file list and Movebank reference tables only;
  no GPS or acceleration data viewed or downloaded).
- **Sensor types:** `gps` and `acceleration` (e-Obs tags). The package
  files cover 2016-2023: GPS as one 478 MB zip, acceleration as eight zips
  of about 2.5 GB in all, so only a derived extract could be committed.
- **Deployments:** 92 in the live study; 72 end `dead`. Of the 92 death
  comments, 31 describe a carcass, remains or logger found (independent
  evidence), 13 say only "vanished" (not evidence of death), and at least
  3 infer the death or its cause from the accelerometer, so would be
  circular labels for an acceleration cue. Recorded causes include
  electrocution (16), predation (15) and vehicle collision (6).
- **Deaths usable for detection** (checked 2026-10-30 against each
  deployment's track end time in Movebank's deployment table): 38
  deployments keep transmitting for 3 days or more after the recorded
  death date. Of these, 13 have a carcass or logger found, 16 have a
  cause recorded but nothing found, 8 have neither, and 1 infers the
  death from acceleration. 21 tracks stop on the day of death, so they
  hold no carcass period.
- **Package against live study:** only 16 deaths fall inside the
  package's 2016-2023 files, and only about 10 of those keep
  transmitting after death; most birds were tagged in 2013-14 and died
  within a year. The full set needs the live study (CC BY, downloadable
  with a Movebank account), so a committed derived extract would carry
  the CC BY attribution.
- **Animals and schedule:** all 92 tagged as nestlings (first-year
  migrants, mostly dying in Spain, France and Morocco); 89 record
  acceleration; GPS and acceleration off from 20:00 to 02:00 GPS time on
  every tag. About 1,380 animal-months in all.

## Movebank sensor scan (2026-10-30)

Studies listed through the Movebank API with a personal login: 8,835 in
all, 706 CC0 or CC BY. Of these, 140 record GPS together with an
acceleration or accessory sensor. Reference tables were read for the 86
with at least 10 deployments. Only the stork study above has more than
11 deployments ending `dead`.

53 further studies returned reference data only after the account
holder accepted their licence terms, which was done through the API on
2026-10-30. Every one is plain CC0 or CC BY under Movebank's standard
terms (cite CC BY data; owners encourage contact and offered credit for
new analyses). Their individual tables (death date, last timestamp,
cause, comments) were read; no tracks were.

- Bobcat habitat connectivity, central California (study 5175345606,
  CC0, GPS and ACC): 12 recorded deaths, but every track ends on or
  before the death date, so none can score a detector.
- Other white stork studies: "Fall migration of white storks in 2014"
  (332044860) repeats the SW Germany birds (57 shared rings).
  "MPIAB white stork lifetime tracking" (74496970) shares 11 birds and
  records no death dates. Kosova has no dated deaths with a tail.
- New stork deaths still transmitting 3+ days after death, deduplicated
  by ring against SW Germany (found / cause only / no evidence /
  inferred from ACC):

  | Study | Movebank id | Licence | Found | Cause | None | ACC |
  | --- | --- | --- | --- | --- | --- | --- |
  | LifeTrack White Stork Rheinland-Pfalz | 76367850 | CC BY | 12 | 14 | 4 | 1 |
  | LifeTrack White Stork Bavaria | 24442409 | CC BY | 6 | 9 | 5 | 3 |
  | LifeTrack White Stork Vorarlberg | 173641633 | CC BY | 2 | 1 | 2 | 0 |
  | LifeTrack White Stork Oberschwaben | 212096177 | CC BY | 1 | 0 | 4 | 0 |

  With SW Germany (14 / 17 / 8 / 1 by the same rules) that is about 35
  deaths with a found carcass or logger and a post-death tail, across
  five populations. "Found" is a keyword match on comments and needs a
  manual check. Most birds are tagged as nestlings; Rheinland-Pfalz
  includes 7 adults, and Bavaria leaves most life stages blank.
  Rheinland-Pfalz alone records 32 electrocutions.

## LifeTrack White Stork populations (`raw/storks/`)

Licence check, 2026-10-31, for the stork case study, made before any
track was downloaded. The extract itself is described under "Stork
extract" below.

- **Source of the extract:** the five live Movebank studies, not the
  published packages, which hold too few of the deaths (see the SW
  Germany entry above). The committed derived extract will be CC BY 4.0
  with the citations below.
- **Live-study licence:** `CC_BY` on all five (Movebank `study` table,
  read through the API with the owner's login), with no custom licence
  terms. Movebank's CC BY option is CC BY 4.0
  (<https://creativecommons.org/licenses/by/4.0/>), which allows sharing
  adapted material with credit, a licence link and a note of changes.
- **Movebank terms:** the General Movebank Terms of Use
  (<https://www.movebank.org/cms/movebank-content/general-movebank-terms-of-use>,
  last updated March 2020) need no owner permission for publicly
  downloadable CC BY studies but require citation, and strongly
  encourage contacting the owners about new analyses. The user agreement
  (<https://www.movebank.org/cms/movebank-content/data-policy>) adds no
  limit on redistribution.
- **Published packages:** each study also has a 2024 repository package,
  licensed CC0 1.0 on DataCite. They are the DOIs to cite.

| Study | Movebank id | Package DOI | Citation (data) |
| --- | --- | --- | --- |
| LifeTrack White Stork SW Germany | 21231406 | <https://doi.org/10.5441/001/1.ck04mn78_2> | Fiedler W, Flack A, Schäfle W, Keeves B, Quetting M, Eid B, Schmid H, Wikelski M. 2024. Data from: Study "LifeTrack White Stork SW Germany" (2013-2023). Movebank Data Repository. |
| LifeTrack White Stork Bavaria | 24442409 | <https://doi.org/10.5441/001/1.v1cs4nn0_2> | Fiedler W, Leppelsack E, Leppelsack H, Stahl T, Wieding O, Wikelski M. 2024. Data from: Study "LifeTrack White Stork Bavaria" (2014-2023). Movebank Data Repository. |
| LifeTrack White Stork Rheinland-Pfalz | 76367850 | <https://doi.org/10.5441/001/1.4192t2j4_2> | Fiedler W, Hilsendegen C, Reis C, Lehmann J, Hilsendegen P, Schmid H, Wikelski M. 2024. Data from: Study "LifeTrack White Stork Rheinland-Pfalz" (2015-2023). Movebank Data Repository. |
| LifeTrack White Stork Vorarlberg | 173641633 | <https://doi.org/10.5441/001/1.71r7pp6q_2> | Fiedler W, Niederer W, Schönenberger A, Flack A, Wikelski M. 2024. Data from: Study "LifeTrack White Stork Vorarlberg" (2016-2023). Movebank Data Repository. |
| LifeTrack White Stork Oberschwaben | 212096177 | <https://doi.org/10.5441/001/1.c42j3js7_2> | Fiedler W, Flack A, Schmid A, Reinhard U, Wikelski M. 2024. Data from: Study "LifeTrack White Stork Oberschwaben" (2014-2023). Movebank Data Repository. |

All five studies name Aikens et al. 2024 (PNAS,
<https://doi.org/10.1073/pnas.2306389121>) as describing the data, and
Movebank asks for Kays et al. 2022 (Methods Ecol Evol,
<https://doi.org/10.1111/2041-210X.13767>) to be cited too.

### Stork extract

Fetched 2026-11-11 from the five live studies through Movebank's REST
API by `scripts/fetch_movebank.py` (`make fetch-storks`; optional, needs
a Movebank account). It is **adapted material under CC BY 4.0**: cite the
packages above, and note that the rows below are reduced from the
studies' events, not copies of them.

The studies hold tens of millions of events (GPS fixes every 5 to 20
minutes with 1 Hz bursts, and an acceleration burst every 2 to 10
minutes), so the events are reduced to one row per UTC clock hour.
Events from 2026-11-01 00:00 UTC on are left out, so a rerun gives the
same rows for birds still transmitting.

- `<study>-gps-N.csv.gz`: the first fix of each hour that Movebank does
  not flag as an outlier (`visible`) and that has a position, with its
  height, ground speed, accuracy estimate, temperature, battery voltage
  and on-board activity count where the tag reports them, text unchanged.
  `fixes_in_hour` counts the usable fixes the hour held.
- `<study>-acc-N.csv.gz`: one row per hour, axis set-up and sampling
  rate, from the raw e-obs bursts, in raw tag units (uncalibrated).
  `bursts` and `burst_samples` (readings per axis in a burst, median);
  `mean_x/y/z`, the mean of the bursts' per-axis means (posture);
  `between_x/y/z`, the standard deviation of those means across the
  hour's bursts (posture change); `spread_min/median/max`, the smallest,
  median and largest within-burst spread, where a burst's spread is the
  square root of its summed per-axis variances (movement). The raw
  readings are not kept: a cue needing burst-level timing needs a
  re-fetch.
- `<study>-individuals.csv`, `-deployments.csv`, `-tags.csv`: Movebank's
  reference tables with the columns named in the script (no names of
  people, tag owners or IMEI numbers), as returned on the fetch date.
- `extract.json`: the cut-off, the attributes requested per study, the
  part files, and per animal the events read, dropped and kept.

Each `.csv.gz` is a gzip file of joined members (the header, then one
per animal in ascending Movebank ID), which any gzip reader opens as one
CSV. Rows carry Movebank's numeric `individual_id`, `deployment_id` and
`tag_id`, which key into the reference tables.

| Study | Movebank id | Animals | Fixes read | GPS rows | Bursts read | Acceleration rows | Parts, MB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SW Germany | 21231406 | 94 | 13,487,188 | 618,838 | 14,763,226 | 663,902 | 29.3 |
| Bavaria | 24442409 | 91 | 7,663,531 | 698,640 | 11,858,113 | 654,966 | 32.1 |
| Rheinland-Pfalz | 76367850 | 108 | 19,659,176 | 842,912 | 18,184,822 | 825,440 | 38.7 |
| Vorarlberg | 173641633 | 28 | 10,472,420 | 280,102 | 4,515,181 | 302,699 | 13.8 |
| Oberschwaben | 212096177 | 18 | 2,645,261 | 212,766 | 1,774,547 | 135,312 | 7.5 |
| All | | 339 | 53,927,576 | 2,653,258 | 51,095,889 | 2,582,319 | 121.4 |

"Animals" counts rows of each individual table, including the few with
no events. No burst was unreadable; five were flagged as outliers.

Completeness checks (2026-11-12):

- GPS: Movebank's own `number_of_events` per animal counts its visible
  fixes with a position, which is what the GPS reduction counts before
  thinning; `extract.json` lists under `incomplete` any animal (ended
  before the cut-off) where the two differ. All five lists are empty.
  The check caught one animal whose response Movebank had ended early
  without an error (1,248 of 44,850 fixes); it was fetched again and
  now matches.
- Acceleration: Movebank publishes no burst count, so each animal and
  calendar year was probed for any burst later than the last hour held
  (540 requests, by hand, not part of the script). None was found.

The held-out populations (`data/splits.csv`) were fetched by the same
run under the same rules; the script prints row counts only, and none of
their tracks has been viewed.

## Stork split (`data/splits.csv`)

Fixed 2026-10-31, before any stork track was downloaded, from the
reference-data counts above only. Whole populations are held out:
SW Germany and Bavaria tune (about 20 found deaths), Rheinland-Pfalz,
Vorarlberg and Oberschwaben are scored once (about 15). Holding out
three populations keeps the scored result from resting on one site,
though Rheinland-Pfalz supplies most of it. "Fall migration of white
storks in 2014" is excluded as a repeat of SW Germany.

Ring check (2026-10-31, individual tables of all five studies via the
Movebank API): all 339 individuals carry a ring in one format (country
code and number, e.g. `DER AY620`), and no ring appears in more than one
study, so no bird can sit on both sides. Some birds have two individual
records within one study (SW Germany's `DER A1A26`); they stay on one
side and are merged when labelling.

## Label overrides (`data/labels.csv`)

Deaths recorded only in a deployment's comments, not in its
`deployment-end-type`, found by reading the vulture reference data
(CC0, as above). Each row quotes the comment it relies on. Evaluation
uses these labels in place of the end type; nothing parses comments in
code.

The three Kruger elephants recorded `dead` (also CC0, as above) died
months after their tracks end: the collars stopped in August 2009, and
the end comments date the deaths between late 2009 and April 2012. They
are labelled `dead-after-track`. The animal was alive for every fix the
pipeline sees, so the final silence is a collar stopping, not a death to
detect.

### Tag events

`tag-event` marks a dropped, stuck or failing tag or a grounded bird,
which the mortality alert's "or dropped tag" text covers. Each row has an
`event-from` time; alerts still open after it are credited to the event.
Birds and times were chosen from comments and tracks, without viewing
alert outcomes, except that the post-mortem had already named
`CAT_BLVU_121784`, `EAX_BLVU_121786` and `VPC_BLVU_283`. Both thresholds
below are provisional.

- **Comment evidence plus a final still run.** The end comment names a
  fault, or says the bird was seen alive after the tag stopped, and the
  track ends in a run of still bouts of at least 7 days each, each
  starting within 24 h of the last and the run ending within 7 days of
  the last fix. `event-from` is the start of the run: `MAT_BLVU_68354`,
  `PMV_BLVU_68350`, `VPC_BLVU_283`.
- **Grounded bird.** `CAT_BLVU_121784` was caught unable to fly. The
  comment gives no onset, so `event-from` is its first still bout past
  the 36 h watch window; its earlier bouts stop at 27 h.
- **Track only.** A still bout over 60 days, beyond what a living bird
  plausibly does, counts without a comment: `EAX_BLVU_121786` (515 days;
  the next longest non-dead bout is 44 days). The row says it is not a
  quotation.

Reviewed and not labelled, because no still period can be tied to the
event: `MHM_BLVU_68349` ("questionable xmitter data in later years",
undated), `MHT_BLVU_68348` ("intermittent readings, low voltage",
undated) and `MHX_BLVU_68351`, `PMP_BLVU_68356`, `LAL_BLVU_68348`,
`AJM_BLVU_111944`, `VLM_BLVU_281` (tag failed, fell off or bird seen
later, but no week-plus bout near the end of the track). They stay
`alive`.

## Park boundaries (`raw/boundaries/`)

- **Source:** OpenStreetMap, via the public Overpass API
  (<https://overpass-api.de/>), fetched by `scripts/fetch_boundaries.py`.
- **Licence:** Open Database Licence (ODbL 1.0),
  <https://opendatacommons.org/licenses/odbl/1-0/>. Attribution:
  "© OpenStreetMap contributors". Share-alike: these files, and anything
  derived from them as a database, stay under the ODbL, apart from the
  rest of the repository (MIT code, CC0 tracking data). Figures drawn from them carry the
  attribution.
- **Retrieved:** 2026-10-19.
- **Files:**
  - `raw/boundaries/etosha.geojson` - Etosha National Park, relation
    2982497 (Wikidata Q675633). One polygon, 419 vertices, about
    23,000 km² (published area 22,270 km²).
  - `raw/boundaries/kruger.geojson` - Kruger National Park, relation
    1752987 (Wikidata Q24451). One polygon, 1,688 vertices, about
    19,100 km² (published area about 19,500 km²).
- **Processing:** each relation's outer member ways are joined into
  polygons and inner ways cut out as holes (shapely `polygonize`);
  coordinates are rounded to 6 decimal places (about 0.1 m). Relations
  were found by name and checked against their Wikidata IDs.
- **Note:** Kruger's relation is the national park alone. Its western
  edge borders the Associated Private Nature Reserves (Sabi Sand,
  Timbavati and others), which are unfenced from Kruger, so crossings
  there are real but not operationally meaningful; evaluation reports
  them as such.

## AWS list prices (`prices/aws-eu-west-2.json`)

- **Source:** AWS's public Price List files
  (<https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json>),
  no account needed, fetched by `scripts/fetch_prices.py` (`make prices`).
  Each price records its offer file URL and publication date.
- **Licence:** published list prices, reproduced as facts with their
  source and date; AWS's site terms apply to the files themselves. Only
  the ten prices the cost report uses are kept.
- **Retrieved:** 2026-10-22 (offers published 2026-09-11 to 2026-10-16).
- **Free tier:** allowances written into the price list (SNS's first
  1,000 emails and 1M requests, DynamoDB's first 25 GB) are read from it;
  those that are not (Lambda's 1M requests and 400,000 GB-seconds, SQS's
  1M requests, CloudWatch Logs' 5 GB) are copied from each service's
  pricing page, checked 2026-10-22, and named with their page.
- **Note:** list prices change; the report states the snapshot's date,
  and a newer snapshot changes the figures without changing the usage.
