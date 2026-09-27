# Findings

Running record, newest first. Each finding names the script and table it
comes from. Nothing here is scored against the Sentinel-1 image yet; these are
first looks, and they are written so they can be proved wrong.

## 4. The radar's new open water lies in farmland; the flooded belt is hidden from it (27 Sep 2026)

`studies/ahmedabad/sar.py`; exhibit `exhibits/out/EX-1.png`; tables
`outputs/tables/sar_e1_summary.json`, `outputs/tables/sar_e1_places.csv`.

The 25 July track-B image, set against the mean of 1 and 13 July (VV, gamma0,
10 m), shows **5,638 ha of new open water**: 11.8% of the ground the radar can
judge. **98.5% of it is cropland.** Thresholds: a fall of 4.8 dB or more and
25 July VV at or below −12.8 dB, both from Otsu over the 67 most-darkened
640 m tiles. Half of that water (49.9%) was still dark on 6 August.

Around the worst-hit localities, almost none of the judgeable ground turned to
open water (within 1.5 km: Bopal 1.5%, Ghuma 0.3%, Shela 2.8%, Sarkhej 3.7%).
The radar can judge only 23–60% of the ground there; the rest is built-up,
which is excluded. The open ground that is judgeable got *wetter* (median
+1.5 to +2.2 dB), not flooded.

Built-up ground brightened everywhere (median built-up change +1.9 dB across
the strip), more in the west (+2.1 to +2.6 dB at Bopal, Ghuma, Shela, Sarkhej
and Makarba) than further east (+1.6 to +1.8 dB at Jodhpur, Vejalpur, Thaltej,
Bodakdev and Gota). **That gradient does not track flooding.** Jodhpur and
Vejalpur are among the worst hit in the press, and Thaltej flooded badly on
local accounts, yet they brightened least. On its own, GRD brightening is not
an urban flood indicator here. Building type and viewing geometry are the
likelier causes.

*Correction, 27 Sep 2026 (same day).* The first version of this finding, and
mark INF 4 in EX-1, compared the west belt against Thaltej, Bodakdev and Gota
as "less affected". Nothing supported that choice: those places were simply
absent from the worst-hit lists. Thaltej had 7.68 in of rain on 23 July
(top ten, DeshGujarat), and local accounts put it among the badly flooded
areas. With Jodhpur and Vejalpur added, the comparison reverses its meaning,
as above. EX-1 has been re-rendered with the corrected mark.

**Recurring July water (DESIGN D13).** The same test, with the same
thresholds, applied to the 2025 same-season scenes (S1A, same track; 23 Jul
2025 had 1.6 mm) flags **15.2%** of the E1 open water (854 ha), leaving
4,784 ha. A looser rule, "dark on 23 Jul 2025", flags **41.3%**. The strict
rule misses paddy transplanted earlier in 2025, which stays dark in both
reference and late image; for picking out *paddy land*, the loose rule may be
the better test. That choice is open (see session notes); the strict rule is
what the 30 m product currently uses.

**Barrage.** At 15:00 on 23 July, the Vasna barrage stood at 124.50 ft, with
5,578 cusecs released through 20 gates (Gujarat Samachar live blog). That is
below the ~128 ft normal level, and it contradicts the 134–135 ft that DESIGN §1
took from one unnamed official (Counterview), at least for that afternoon.

**Consequence for validation (DESIGN §5.4, D9).** Scored on the observable
mask as designed, the E1 test would be decided almost entirely on farmland.
The two competing explanations there are rain ponding and paddy flooded for
transplanting, and neither is the urban flooding the project asks about. This
needs a decision before any model is scored; the options are in the session
notes and will go into DESIGN §9.

**Method notes.**
- GLO-30 heights were converted from the EGM2008 geoid to ellipsoidal
  (−54.0 to −55.5 m here) before terrain correction, since sarsen reads DEM
  heights as ellipsoidal.
- sarsen writes south-up rasters. The first detection run reprojected
  WorldCover onto that grid and misaligned it (6,604 ha instead of 5,944).
  Everything is now flipped to north-up on read.
- Trees are excluded from the observable mask, in addition to DESIGN §5.3's
  three exclusions (C-band sees little water under canopy), and so are pixels
  with no WorldCover class.

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
