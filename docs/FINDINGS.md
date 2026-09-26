# Findings

Running record, newest first. Each finding names the script and table it
comes from. Nothing here is scored against the Sentinel-1 image yet; these are
first looks, and they are written so they can be proved wrong.

## 3. The flooded west doesn't stand out in the terrain (27 Sep 2026)

`studies/ahmedabad/terrain.py`, figure `outputs/figures/t2_terrain_west.png`.

Within 1.5 km of each locality, on FABDEM (bare earth):

| | Share of ground in depressions ≥ 10 cm | Median HAND |
|---|---|---|
| Bopal, Ghuma, Shela | 3.8–4.8% | 0.8–1.1 m |
| Jodhpur, Vejalpur | 3.1–5.0% | 0.7–1.0 m |
| Sarkhej, Makarba | 10.6–12.5% | 0.9 m |
| Kalupur, Asarwa (east) | 8.5–8.8% | 0.5–1.3 m |
| Maninagar, Naroda (east) | 3.6–6.8% | 1.4–1.5 m |

The localities worst hit on 23–25 July are not more depression-prone than
the east, except Sarkhej and Makarba. HAND is about 1 m or less almost
everywhere, so on its own it can't separate the west from anywhere else.
The largest depressions are mostly peri-urban lakes and pits outside the
city, some 8–12 m deep.

What this suggests, to be tested and not assumed:
- **Rain distribution.** By 4 pm on 23 July the South West Zone had 196 mm,
  twice the 96 mm city average (`data/manual/amc_rain_2026-07.csv`). The
  spatial rain field may matter more than terrain, so M2 and M3 should be
  forced with the gauge pattern, not a uniform total (DESIGN §5.2 already plans this).
- **Drainage.** AMC says Bopal–Ghuma never got a full storm-drain network
  after joining the city (DeshGujarat, 25 Jul). A single citywide drain-loss
  parameter (DESIGN §5.2) can't represent that. A served/unserved split is the
  obvious candidate, and it is a design change to decide before M2 is built.
- **DEM age.** Both DEMs come from TanDEM-X data acquired 2011–15, before much
  of Bopal–Shela was built and before plots were filled. A 30 m model of that
  age may not show the ponding surfaces that exist now.

The expectation in DESIGN §1 ("HAND will largely miss Bopal, and a model that
routes rain into depressions will catch it") is not supported by the terrain
alone. The Sentinel-1 comparison decides it.

## 2. Buildings in GLO-30 invent depressions everywhere (27 Sep 2026)

`studies/ahmedabad/terrain.py`, figure `outputs/figures/t1_dem_depressions.png`,
tables `outputs/tables/depressions_{glo30,fabdem}.csv`.

With pit and depression filling on the same 30 m grid, **24.2%** of the domain
lies in a depression at least 10 cm deep on GLO-30 (45,546 separate
depressions), against **7.7%** on FABDEM (3,186). Around every locality,
GLO-30 puts roughly 25–35% of the ground in depressions, whether or not it
flooded. The gaps between buildings read as ponds. For the pluvial rungs
(M2, M3), GLO-30 carries a built-in bias, and the DEM comparison in the
validation table will show how much it costs.

**HAND drainage threshold.** Checked against OSM rivers, streams, drains and
ditches (canals excluded as engineered; `outputs/tables/stream_threshold_check.csv`).
The share of mapped drainage reproduced within 90 m falls steadily as the
threshold rises (0.73 at 0.25 km², 0.67 at 1 km², 0.21 at 50 km²), with no
plateau. The rule "coarsest threshold keeping ≥ 90% of the best recall" gives
1 km², but with no plateau that is a judgement, not a calibration. OSM rivers
(the Sabarmati, Khari and Meshwa) are burned in as channels, because their
catchments lie mostly outside the domain. HAND is undefined for 4.4% of cells
(no drainage path inside the domain).

## 1. It was still raining when the 25 July image was taken (27 Sep 2026)

`scripts/rain_check.py`, `outputs/tables/s1_antecedent_rain.csv`; details in
`data/README.md` and DESIGN §4, decided as D11.
