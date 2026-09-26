# Data

Nothing under `data/raw/` or `data/interim/` is committed. `python scripts/fetch.py all`
downloads every raw file below (about 320 MB). `data/manual/` holds
hand-transcribed tables and is committed. The `s1` group needs the environment
(`make env`); the other groups use the standard library only. OSM roads and
hospitals are pulled at run time by `hazardnet` and cached, as in Project 1.

| Path (under `data/raw/`) | Source | Access | Licence |
|---|---|---|---|
| `dem/glo30/Copernicus_DSM_COG_10_N2{2,3}_00_E072_00_DEM.tif` | Copernicus GLO-30 DSM, 1° tiles | AWS Open Data, `copernicus-dem-30m` (no signup) | Copernicus DEM licence: free, attribution required |
| `dem/fabdem/N2{2,3}E072_FABDEM_V1-2.tif` | FABDEM v1-2 (Hawker et al. 2022): GLO-30 with buildings and trees removed | Univ. of Bristol, `N20E070-N30E080_FABDEM_V1-2.zip`. The two tiles are cut out of the 1.9 GB zip by HTTP byte range (members are stored uncompressed), CRC-checked | **CC BY-NC-SA 4.0** |
| `wards/datameet_ahmedabad_wards.geojson` | DataMeet `Municipal_Spatial_Data/Ahmedabad/Wards.geojson`, 48 wards | GitHub, pinned to commit `46679b9` (12 Aug 2016, the last change to the file) | CC BY-SA 2.5 IN |
| `s1/<scene>.SAFE/` | Sentinel-1D IW GRDH, E1 track B, four dates (below) | AWS `sentinel-s1-l1c`, anonymous HTTPS. All files except the images are copied whole, under their original SAFE names from `productInfo.json` | Copernicus Sentinel data, free and open. Credit: "Contains modified Copernicus Sentinel data 2026" |
| `s1/e1_scenes.json` | Scene IDs, dates and footprints actually used | written by `fetch.py` | — |
| `era5/era5_hourly_precip_2026-06-25_2026-08-07.json` | ERA5 hourly precipitation, 3 × 3 native 0.25° cells over the domain | Open-Meteo archive API, `models=era5` (no key) | ERA5: Copernicus Climate Change Service; Open-Meteo data CC BY 4.0 |
| `press/*.html`, `press/SOURCES.json` | Snapshots of the pages the E1 rain-gauge and Vasna figures are transcribed from (DESIGN §1, §3) | Publishers' sites | Publishers' copyright. Kept locally as the audit trail for transcribed numbers; never committed or republished |

## Sentinel-1 scenes (E1, track B, S1D, descending, ≈01:09 UTC)

| Date | Role | Scene |
|---|---|---|
| 1 Jul 2026 | pre | `S1D_IW_GRDH_1SDV_20260701T010923_20260701T010948_003473_006234_C550` |
| 13 Jul 2026 | pre | `S1D_IW_GRDH_1SDV_20260713T010924_20260713T010949_003648_006824_7405` |
| 25 Jul 2026 | during | `S1D_IW_GRDH_1SDV_20260725T010925_20260725T010950_003823_006E26_FBB7` |
| 6 Aug 2026 | post | `S1D_IW_GRDH_1SDV_20260806T010925_20260806T010950_003998_00743C_8410` |

`fetch.py` does not hard-code these. It lists the S1D slices for each date that
start in the 01h UTC hour, keeps those whose footprint touches the domain box
(72.35–72.80° E, 22.85–23.20° N), and checks that they share a datatake. On
every date, exactly one slice qualified.

**Windowed reads.** The GRD images are tiled 1024 × 1024 (deflate), not stored
row by row as DESIGN D4 assumed, so the window is cut in both directions. The
domain box is mapped to image rows and columns through the scene's GCPs,
padded by 512 px and snapped to whole tiles: rows 9216–15360, columns 0–3072 on
all four dates. Each measurement file is written at the **full image size as a
sparse GeoTIFF**. Only the window's tiles hold data; the rest read as 0
(no data). Keeping the full shape keeps the file consistent with the product's
annotation XML, so calibration and terrain correction treat it as a normal
product. Compressed bytes read: 184 MB for all eight images (VV + VH × 4),
against the ≈0.8 GB estimated in D4. Each `.SAFE/fetch_window.json` records its
window and byte count.

Checked after fetching: Bopal (72.468° E, 23.030° N) maps to column ~600 and
Sarkhej to ~190 on every date, both inside the window with non-zero data. The
riverfront (72.575° E) maps to column ≈ −470, outside the swath, as DESIGN §4
says: track B stops short of the Sabarmati.

## Transcribed data (`data/manual/`, committed)

Typed from the `press/` snapshots. Every row carries its source file and URL,
and all 51 rain values were checked against the saved page text by script.

- `amc_rain_2026-07.csv`: AMC gauge, zone and city rainfall as the press
  reported it, in the reported unit plus mm. Four reporting windows, which
  **must not be mixed**:
  - 23 Jul 06:00–18:00 IST (DeshGujarat; top-25 stations and city average 127.28 mm)
  - 23 Jul 06:00–16:00 IST (DeshGujarat; zone averages, e.g. South West 196.14 mm, **to 4 pm only**)
  - 23 Jul, period not stated (Gujarat Samachar; Bakrol 14.61 in, much higher
    than DeshGujarat's 11.20, probably a longer window or a later update)
  - 24 h to 06:00 IST (DeshGujarat, dated 25 Jul; city average 62.81 mm).
    The article says "till 6 am on Friday", which was 24 Jul. But its totals
    are lower than the 23 Jul daytime figures and heaviest in the east, so the
    window is taken as **24 Jul 06:00 → 25 Jul 06:00**. That is unconfirmed.
  Source inconsistencies are kept and noted per row. For example, the 23 Jul
  article's text gives Sarkhej 9.17 in and its table gives 11.12 in; the table
  value is kept.
- `vasna_barrage_2026-07.csv`: 11 gates open by 16:00 and 20 by ~18:00 on
  23 Jul, with ~3,600 cusecs outflow (DeshGujarat). The 134–135 ft level comes
  from **one unnamed former official in an opinion column** (Counterview,
  5 Aug), with no date or time for the reading.

**Not yet covered:** gauge totals for 23 Jul 18:00 → 24 Jul 06:00 (ERA5 has
heavy rain overnight), and station locations (the gauge names still need
geocoding before they can force M2/M3).

## Rain before each S1 pass (`scripts/rain_check.py`)

ERA5 hourly rain, maximum over the nine cells, before each pass (full table in
`outputs/tables/s1_antecedent_rain.csv`):

| Pass | 24 h before | 72 h before | Last hour ≥ 1 mm |
|---|---|---|---|
| 1 Jul | 0.3 mm | 0.3 mm | none since 25 Jun |
| 13 Jul | 0.1 mm | 1.0 mm | 118 h before |
| **25 Jul** | **82.1 mm** | **156.6 mm** | **0.2 h before: raining at the pass** |
| 6 Aug | 0.9 mm | 3.1 mm | 85 h before |

So **13 July stays as a pre-flood reference** (no rain on 12–13 July). The
25 July image was **taken during the rain's second day**, not two days after
the peak. ERA5 shows 3–7 mm/h through the morning of 24 Jul (UTC), a second
burst that evening, and 2.5–3 mm/h in the hours before 01:09 UTC on 25 Jul.
ERA5 under-reads convective totals: 60.7 mm on 23 Jul at the Bopal cell, against
a gauge city average of 127 mm. So these figures show *that* it rained, not how much.

## Known gaps
- **Ward file vintage.** The DataMeet file was last changed in 2016 and does not
  contain Bopal or Ghuma, which joined AMC in 2020. H3 hexes are the primary unit (D6).
- **Rain.** No gridded product covers July 2026 at useful resolution. The gauge
  record is press-transcribed, in four windows, and has a 12-hour hole on the
  night of 23 Jul (above).
- **Copernicus DEM attribution text** is to be copied verbatim from the ESA
  licence document into `DATA_LICENSES.md` before anything is published.
- The S1 image **window depends on `DOMAIN_BBOX`** in `fetch.py`. If the model
  domain grows past it, widen the box and rerun `fetch.py s1`; delete the
  `.SAFE` folders first, since a finished scene is skipped.
