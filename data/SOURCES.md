# Data sources

One entry per dataset: name, URL, DOI, licence, date retrieved, and what
was extracted. Only CC0 or CC-BY data is committed.

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
  - `raw/JACKAL.md` - the package README (published as `README.txt`)
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
