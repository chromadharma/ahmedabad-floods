# Data

Nothing under `data/raw/` or `data/interim/` is committed. `python scripts/fetch.py all`
downloads every raw file below (about 320 MB). The `s1` group needs the environment
(`make env`); the other groups use the standard library only. OSM roads and
hospitals are pulled at run time by `hazardnet` and cached, as in Project 1.

| Path (under `data/raw/`) | Source | Access | Licence |
|---|---|---|---|
| `dem/glo30/Copernicus_DSM_COG_10_N2{2,3}_00_E072_00_DEM.tif` | Copernicus GLO-30 DSM, 1° tiles | AWS Open Data, `copernicus-dem-30m` (no signup) | Copernicus DEM licence: free, attribution required |
| `dem/fabdem/N2{2,3}E072_FABDEM_V1-2.tif` | FABDEM v1-2 (Hawker et al. 2022): GLO-30 with buildings and trees removed | Univ. of Bristol, `N20E070-N30E080_FABDEM_V1-2.zip`. The two tiles are cut out of the 1.9 GB zip by HTTP byte range (members are stored uncompressed), CRC-checked | **CC BY-NC-SA 4.0** |
| `wards/datameet_ahmedabad_wards.geojson` | DataMeet `Municipal_Spatial_Data/Ahmedabad/Wards.geojson`, 48 wards | GitHub, pinned to commit `46679b9` (12 Aug 2016, the last change to the file) | CC BY-SA 2.5 IN |
| `s1/<scene>.SAFE/` | Sentinel-1D IW GRDH, E1 track B, four dates (below) | AWS `sentinel-s1-l1c`, anonymous HTTPS. All files except the images are copied whole, under their original SAFE names from `productInfo.json` | Copernicus Sentinel data, free and open. Credit: "Contains modified Copernicus Sentinel data 2026" |
| `s1/e1_scenes.json` | Scene IDs, dates and footprints actually used | written by `fetch.py` | — |
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

## Known gaps
- **Ward file vintage.** The DataMeet file was last changed in 2016 and does not
  contain Bopal or Ghuma, which joined AMC in 2020. H3 hexes are the primary unit (D6).
- **Rain.** No gridded product covers July 2026 at useful resolution. The AMC
  gauge totals have to be transcribed from `press/` into
  `data/manual/`, with each value's source URL (D5). Not done yet.
- **Rain on 12–13 July** is unchecked. If it rained, 13 July is dropped as a
  pre-flood reference and 1 July stands alone (DESIGN §4).
- **Copernicus DEM attribution text** is to be copied verbatim from the ESA
  licence document into `DATA_LICENSES.md` before anything is published.
- The S1 image **window depends on `DOMAIN_BBOX`** in `fetch.py`. If the model
  domain grows past it, widen the box and rerun `fetch.py s1`; delete the
  `.SAFE` folders first, since a finished scene is skipped.
