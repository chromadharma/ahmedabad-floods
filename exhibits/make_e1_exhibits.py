"""Build the E1 observed-extent exhibit: rasters, annotations and spec.

    python exhibits/make_e1_exhibits.py
    python "<imagery-exhibits skill>/scripts/render.py" exhibits/spec.json

Every mark is derived from an analysis output (studies/ahmedabad/sar.py and
outputs/tables/sar_e1_places.csv) or a cited report, never placed by eye.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import transform as shp_transform

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from studies.ahmedabad import sar  # noqa: E402

DATA = HERE / "data"
CRS = "EPSG:32643"
VIEW = (72.40, 22.962, 72.56, 23.058)         # panel extent, lon/lat, at the 2x2 panel aspect (~1.65)
CLIP = (72.37, 22.91, 72.59, 23.13)          # rasters extend past the panel
SCENES = json.loads((ROOT / "data" / "raw" / "s1" / "e1_scenes.json").read_text())
SCENE = {s["date"]: s["id"] for s in SCENES}
SUMMARY = json.loads((ROOT / "outputs" / "tables" / "sar_e1_summary.json").read_text())
T_CHANGE = abs(SUMMARY["t_change_db"])
ACQ = {"2026-07-01": "2026-07-01 01:09Z", "2026-07-13": "2026-07-13 01:09Z",
       "2026-07-25": "2026-07-25 01:09Z", "2026-08-06": "2026-08-06 01:09Z"}
SENSOR = "Sentinel-1D C-SAR IW GRDH"
PROC = ("sarsen 0.9.6 terrain correction to gamma0 on GLO-30 (geoid-corrected to ellipsoid), "
        "10 m UTM 43N; Lee 5x5 filter")
to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
to_geo = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)


def _clip_write(arr, prof, name) -> str:
    W, S, E, N = to_utm.transform(CLIP[0], CLIP[1]) + to_utm.transform(CLIP[2], CLIP[3])
    win = from_bounds(W, S, E, N, prof["transform"]).round_offsets().round_lengths()
    sub = arr[win.row_off:win.row_off + win.height, win.col_off:win.col_off + win.width]
    p = prof | dict(width=win.width, height=win.height, count=1, dtype="float32", nodata=np.nan,
                    transform=rasterio.windows.transform(win, prof["transform"]), compress="deflate")
    DATA.mkdir(parents=True, exist_ok=True)
    with rasterio.open(DATA / f"{name}.tif", "w", **p) as dst:
        dst.write(sub.astype("float32"), 1)
    return f"data/{name}.tif"


def rasters() -> dict:
    db = lambda a: 10 * np.log10(a)
    g13, prof = sar._read_g("2026-07-13", "VV")
    g25, _ = sar._read_g("2026-07-25", "VV")
    paths = {"pre": _clip_write(db(sar.lee(g13)), prof, "vv_20260713_db"),
             "during": _clip_write(db(sar.lee(g25)), prof, "vv_20260725_db")}
    with rasterio.open(sar.OUT / "e1_change_vv_db.tif") as s:
        paths["change"] = _clip_write(s.read(1), s.profile, "vv_change_db")
    with rasterio.open(sar.OUT / "e1_classes_10m.tif") as s:
        cls, cprof = s.read(1), s.profile
    disp = np.full(cls.shape, np.nan, dtype="float32")
    disp[cls == sar.FLOOD] = -10.0             # drawn in the "fell" colour
    disp[cls == sar.BUILT_UP_FLAG] = 10.0      # drawn in the "rose" colour
    paths["classes"] = _clip_write(disp, cprof, "e1_classes_display")
    return paths


def _in_view(geom_utm) -> bool:
    W, S, E, N = to_utm.transform(VIEW[0], VIEW[1]) + to_utm.transform(VIEW[2], VIEW[3])
    from shapely.geometry import box
    return box(W, S, E, N).contains(geom_utm.centroid)


def annotations() -> dict:
    feats = []
    with rasterio.open(sar.OUT / "e1_classes_10m.tif") as s:
        cls, T = s.read(1), s.transform
    # OBSERVED: the 1 km square in view with the highest share of new open water
    # among the ground the radar could judge (>= 50% judgeable), clear of the
    # scale bar (lower-left of each panel). Water here is scattered, so a square
    # carries the observation better than any single small cluster.
    wc = sar._worldcover_on(dict(height=cls.shape[0], width=cls.shape[1], transform=T, crs=CRS))
    (vx0, vy0), (vx1, vy1) = to_utm.transform(VIEW[0], VIEW[1]), to_utm.transform(VIEW[2], VIEW[3])
    best = None
    for x in np.arange(vx0 + 500, vx1 - 1500, 250):
        for y in np.arange(vy0 + 500, vy1 - 1500, 250):
            if x < vx0 + 0.45 * (vx1 - vx0) and y < vy0 + 0.3 * (vy1 - vy0):
                continue                                    # scale-bar corner
            c0, r1 = ~T * (x, y); c1, r0 = ~T * (x + 1000, y + 1000)
            sub = cls[int(r0):int(r1), int(c0):int(c1)]
            obs = np.isin(sub, (sar.DRY, sar.FLOOD))
            if obs.mean() < 0.5:
                continue
            share = float((sub == sar.FLOOD).sum() / obs.sum())
            if best is None or share > best[0]:
                best = (share, x, y, wc[int(r0):int(r1), int(c0):int(c1)])
    share, x, y, wsub = best
    c0, r1 = ~T * (x, y); c1, r0 = ~T * (x + 1000, y + 1000)
    fsub = cls[int(r0):int(r1), int(c0):int(c1)] == sar.FLOOD
    crop = float((wsub[fsub] == 40).mean())
    from shapely.geometry import box as sbox
    sq = sbox(x, y, x + 1000, y + 1000)
    feats.append(dict(type="Feature", geometry=mapping(shp_transform(to_geo.transform, sq)),
                      properties=dict(ann_id="e1-01", exhibit="EX-1", panel="D", **{"class": "OBSERVED"},
                                      label=(f"New open water on {share:.0%} of the judgeable ground in this 1 km "
                                             f"square; {crop:.0%} of that water is on cropland"),
                                      sensor=SENSOR, acq_utc=ACQ["2026-07-25"], gsd_m=10,
                                      source=SCENE["2026-07-25"],
                                      geom_precision="1 km analysis square, not a feature outline")))
    # LIMIT: the swath's east edge, from the valid-data mask, within the view latitudes
    valid = cls != sar.NODATA
    pts = []
    for r in range(0, cls.shape[0], 40):
        c = np.flatnonzero(valid[r])
        if c.size:
            x, y = T * (c[-1] + 0.5, r + 0.5)
            lon, lat = to_geo.transform(x, y)
            if VIEW[1] <= lat <= VIEW[3]:
                pts.append((lon, lat))
    feats.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=pts[::-1]),
                      properties=dict(ann_id="e1-02", exhibit="EX-1", panel="B", **{"class": "LIMIT"},
                                      label="Edge of the radar swath: nothing east of this line was imaged",
                                      evidence="east edge of valid gamma0 pixels, 25 Jul scene",
                                      geom_precision="10 m")))
    # CLAIM: the belt the press calls worst hit
    places = json.loads((ROOT / "data" / "raw" / "places" / "nominatim_places.json").read_text())
    belt = MultiPoint([to_utm.transform(float(places[k]["lon"]), float(places[k]["lat"]))
                       for k in ("Bopal", "Ghuma", "Shela")]).convex_hull.buffer(700)
    feats.append(dict(type="Feature", geometry=mapping(shp_transform(to_geo.transform, belt)),
                      properties=dict(ann_id="e1-03", exhibit="EX-1", panel="D", **{"class": "CLAIM"},
                                      label="Claimed: Bopal-Ghuma-Shela worst hit, water about 3 ft deep for about 3 days",
                                      source="DeshGujarat 25 Jul 2026 (AMC); Counterview 5 Aug 2026 (opinion column)",
                                      geom_precision="hull of OSM locality points, buffered 700 m; the claim names places, not an outline")))
    # INFERRED: built-up brightening runs west-to-east and does not track the
    # reported flooding (Jodhpur and Vejalpur, worst hit in the press, brightened least)
    rows = {r["place"]: r for r in csv.DictReader(open(ROOT / "outputs" / "tables" / "sar_e1_places.csv"))}
    west = [float(rows[k]["builtup_median_change_db"]) for k in ("Bopal", "Ghuma", "Shela", "Sarkhej", "Makarba")]
    east = [float(rows[k]["builtup_median_change_db"]) for k in ("Jodhpur", "Vejalpur", "Thaltej", "Bodakdev")]
    jx, jy = to_utm.transform(float(places["Jodhpur"]["lon"]), float(places["Jodhpur"]["lat"]))
    lon, lat = to_geo.transform(jx - 600, jy + 300)
    feats.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[lon, lat]),
                      properties=dict(ann_id="e1-04", exhibit="EX-1", panel="D", **{"class": "INFERRED"},
                                      label=(f"Built-up brightening falls west to east ({min(west):+.1f} to {max(west):+.1f} dB, "
                                             f"then {min(east):+.1f} to {max(east):+.1f} dB) even where the east flooded: "
                                             "not a flood signal on its own"),
                                      evidence=("median built-up change within 1.5 km (sar_e1_places.csv); Jodhpur and "
                                                "Vejalpur are worst hit in the press yet brightened least."))))
    return dict(type="FeatureCollection", features=feats)


def spec(paths: dict) -> dict:
    meta = lambda date, product: dict(sensor=SENSOR, product=product, acq_utc=ACQ[date], gsd_m=10,
                                      scene=SCENE[date], processing=PROC)
    layers = {
        "vv_pre": dict(type="raster", style="sar_db", path=paths["pre"], meta=meta("2026-07-13", "VV gamma0 dB")),
        "vv_during": dict(type="raster", style="sar_db", path=paths["during"],
                          meta=meta("2026-07-25", "VV gamma0 dB")),
        "vv_change": dict(type="raster", style="change_db", threshold_db=round(T_CHANGE, 1), path=paths["change"],
                          meta=dict(meta("2026-07-25", "VV change vs mean of 1 and 13 Jul, dB"),
                                    acq_utc="2026-07-25 01:09Z vs 2026-07-01 and 2026-07-13 01:09Z")),
        "classes": dict(type="raster", style="change_db", threshold_db=1, path=paths["classes"],
                        meta=dict(meta("2026-07-25", "classified: new open water / built-up brightening"),
                                  processing=PROC + "; classes from studies/ahmedabad/sar.py")),
        "world": dict(type="vector", style="world",
                      path="C:/Program Files/QGIS 4.0.2/apps/qgis/resources/data/world_map.gpkg|layername=countries"),
    }
    ext = list(VIEW)
    ex = dict(
        id="EX-1", layout="2x2",
        title="On 25 July the radar's new open water lay in farmland; the flooded built-up belt was hidden from it",
        subtitle=("Western Ahmedabad (Bopal, Ghuma, Shela, Sarkhej). Radar VV before and during the flood, "
                  "same orbit and geometry; change; and the classified result."),
        panels=[
            dict(extent=ext, layers=["vv_pre"], meta_from="vv_pre", caption="Radar VV, 13 Jul (before)"),
            dict(extent=ext, layers=["vv_during"], meta_from="vv_during",
                 caption="Radar VV, 25 Jul 06:39 IST, in light rain"),
            dict(extent=ext, layers=["vv_change", "vv_during"], meta_from="vv_change",
                 caption=f"VV change from the 1 and 13 Jul mean, beyond {T_CHANGE:.1f} dB"),
            dict(extent=ext, layers=["classes", "vv_during"], meta_from="classes",
                 caption="Classified: new open water; built-up that brightened 3 dB or more"),
        ],
        locator=dict(layers=["world"], extent=[70.5, 21.5, 74.5, 24.5], caption="Gujarat, India; box = panel A"),
        data_key=(f"C: VV fell (dark blue) or rose (green) by {T_CHANGE:.1f} dB or more (Otsu). D, dark blue: "
                  f"new open water (also 25 Jul VV at most -{abs(SUMMARY['t_water_db']):.1f} dB; built-up, trees, "
                  "permanent water excluded). D, green: built-up that brightened 3 dB or more (chosen; see INF 4)."),
        cannot_show=("Water between buildings: built-up land (WorldCover 2021) is excluded, so Bopal's streets are "
                     "not scored. Rain at the pass roughens water and can hide it. Flood water in farmland and "
                     "paddy flooded for transplanting look alike; 50% was still dark on 6 Aug. The swath misses "
                     "the river and the east. 10 m pixels miss underpasses."),
    )
    return dict(case="Ahmedabad floods E1, 23-25 Jul 2026", author="Sahasrik Ragani", crs=CRS, dpi=200,
                project="e1_exhibits.qgz", out_dir="out", annotations="annotations.geojson",
                annotations_gpkg="annotations.gpkg",
                credits=["Contains modified Copernicus Sentinel data 2026", "ESA WorldCover 2021 (CC BY 4.0)",
                         "Copernicus GLO-30 DEM", "(c) OpenStreetMap contributors (ODbL)"],
                layers=layers, exhibits=[ex])


if __name__ == "__main__":
    paths = rasters()
    (HERE / "annotations.geojson").write_text(json.dumps(annotations(), indent=1, ensure_ascii=False),
                                              encoding="utf-8")
    (HERE / "spec.json").write_text(json.dumps(spec(paths), indent=1, ensure_ascii=False), encoding="utf-8")
    print("  wrote exhibits/spec.json, annotations.geojson, data/*.tif")
