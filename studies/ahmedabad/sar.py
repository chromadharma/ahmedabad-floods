"""Sentinel-1 E1 observed flood extent (DESIGN §5.3).

    python -m studies.ahmedabad.sar dem            # 10 m ellipsoidal-height DEM over the S1 strip
    python -m studies.ahmedabad.sar rtc [date pol] # terrain-corrected gamma0 per scene and polarisation
    python -m studies.ahmedabad.sar all

Geocoding uses GLO-30 (a surface model, which is what the radar sees),
resampled to 10 m. GLO-30 heights are relative to the EGM2008 geoid, but
sarsen reads DEM heights as ellipsoidal. Over Ahmedabad the geoid lies about
55 m below the ellipsoid, which would shift every pixel ~75 m across track,
so heights are converted per pixel first.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch import RAW  # noqa: E402

OUT = ROOT / "data" / "interim" / "sar"
CRS = "EPSG:32643"
RES = 10.0
# The part of the domain track B sees: its swath edge crosses the city near
# 72.53-72.55 E (data/README.md), so the strip stops at 72.60 E.
STRIP_BBOX = (72.35, 22.85, 72.60, 23.20)
POLS = ("VV", "VH")


def scenes() -> dict[str, Path]:
    """All fetched scenes by date: the E1 set and the 2025 same-season baseline."""
    out = {}
    for manifest in ("e1_scenes.json", "base2025_scenes.json"):
        f = RAW / "s1" / manifest
        if f.exists():
            out |= {s["date"]: RAW / "s1" / f"{s['id']}.SAFE" for s in json.loads(f.read_text())}
    return out


def make_dem() -> Path:
    import pyproj
    W, S, E, N = transform_bounds("EPSG:4326", CRS, *STRIP_BBOX)
    W, S = np.floor(W / RES) * RES, np.floor(S / RES) * RES
    E, N = np.ceil(E / RES) * RES, np.ceil(N / RES) * RES
    w, h = int((E - W) / RES), int((N - S) / RES)
    transform = from_origin(W, N, RES, RES)
    srcs = [rasterio.open(t) for t in sorted((RAW / "dem" / "glo30").glob("*.tif"))]
    mosaic, mtrans = merge(srcs)
    src_crs = srcs[0].crs
    for s in srcs:
        s.close()
    dem = np.full((h, w), np.nan, dtype="float32")
    reproject(mosaic[0].astype("float32"), dem, src_transform=mtrans, src_crs=src_crs,
              dst_transform=transform, dst_crs=CRS, resampling=Resampling.bilinear,
              dst_nodata=np.nan)
    # geoid undulation on a 100 m lattice, interpolated: it varies < 1 m here
    pyproj.network.set_network_enabled(True)
    to_geo = pyproj.Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    geoid = pyproj.Transformer.from_crs("EPSG:4326+3855", "EPSG:4979", always_xy=True)
    step = 10
    rr, cc = np.mgrid[0:h:step, 0:w:step]
    xs, ys = rasterio.transform.xy(transform, rr.ravel(), cc.ravel())
    lon, lat = to_geo.transform(xs, ys)
    und = np.array(geoid.transform(lon, lat, np.zeros(len(lon)))[2]).reshape(rr.shape)
    from scipy.ndimage import zoom
    und_full = zoom(und, (h / und.shape[0], w / und.shape[1]), order=1)[:h, :w]
    ell = (dem + und_full).astype("float32")
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "dem10_glo30_ellipsoid.tif"
    prof = dict(driver="GTiff", width=w, height=h, count=1, dtype="float32", crs=CRS,
                transform=transform, nodata=np.nan, compress="deflate", tiled=True)
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(ell, 1)
    print(f"  {out.name}: {w} x {h}, geoid undulation {und.min():.2f} to {und.max():.2f} m")
    return out


def rtc(date: str, pol: str) -> Path:
    import sarsen
    safe = scenes()[date]
    out = OUT / f"gamma0_{date}_{pol}.tif"
    if out.exists():
        print(f"  have {out.name}")
        return out
    t0 = time.time()
    product = sarsen.Sentinel1SarProduct(str(safe), measurement_group=f"IW/{pol}")
    sarsen.terrain_correction(product, str(OUT / "dem10_glo30_ellipsoid.tif"),
                              output_urlpath=str(out), correct_radiometry="gamma_bilinear")
    print(f"  {out.name} ({time.time() - t0:.0f} s)")
    return out


# ------------------------------------------------------------------ detection

PRE, DURING, POST = ("2026-07-01", "2026-07-13"), "2026-07-25", "2026-08-06"
ENL = 4.4                 # equivalent number of looks, S1 IW GRDH
TILE = 64                 # px (640 m) for the split-based threshold search
MIN_PX = 5                # drop flood clusters smaller than 5 px (0.05 ha)
DB_UP = 3.0               # built-up brightening, dB: experimental double-bounce flag
# 10 m classes
DRY, FLOOD, PERMANENT, BUILT, TREES, BUILT_UP_FLAG, NODATA = 0, 1, 2, 3, 4, 5, 255
WC_BUILT, WC_TREES, WC_WATER = 50, 10, 80


def _read_g(date: str, pol: str):
    from affine import Affine
    with rasterio.open(OUT / f"gamma0_{date}_{pol}.tif") as s:
        g = s.read(1).astype("float64")
        prof = s.profile
    t = prof["transform"]
    if t.e > 0:       # sarsen writes south-up; flip so every product downstream is north-up
        g = g[::-1]
        prof = prof | dict(transform=Affine(t.a, t.b, t.c, t.d, -t.e, t.f + t.e * g.shape[0]))
    g[~np.isfinite(g) | (g <= 0)] = np.nan
    return g, prof


def lee(img: np.ndarray, size: int = 5) -> np.ndarray:
    """Lee filter for multiplicative speckle (linear power), NaN-aware."""
    from scipy.ndimage import uniform_filter
    valid = np.isfinite(img)
    x = np.where(valid, img, 0.0)
    n = uniform_filter(valid.astype(float), size)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = uniform_filter(x, size) / n
        m2 = uniform_filter(x * x, size) / n
        var = np.maximum(m2 - m * m, 0)
        cu2, ci2 = 1 / ENL, var / (m * m)
        w = np.clip((1 - cu2 / ci2) / (1 + cu2), 0, 1)
    out = m + w * (x - m)
    out[~valid] = np.nan
    return out


def split_otsu(change: np.ndarray, during: np.ndarray, valid: np.ndarray):
    """Otsu thresholds from tiles where change is large (split-based, after
    Martinis et al.): a scene that is mostly unchanged has no second mode for
    Otsu to find. Returns (change threshold, during-backscatter threshold, n tiles)."""
    from skimage.filters import threshold_otsu
    h, w = change.shape
    tiles = []
    for r in range(0, h - TILE, TILE):
        for c in range(0, w - TILE, TILE):
            v = valid[r:r + TILE, c:c + TILE]
            if v.mean() < 0.8:
                continue
            tiles.append((np.nanmean(change[r:r + TILE, c:c + TILE][v]), r, c))
    means = np.array([t[0] for t in tiles])
    cut = np.percentile(means, 5)                     # the 5% of tiles that darkened most
    sel = [t for t in tiles if t[0] <= cut]
    pool_c = np.concatenate([change[r:r + TILE, c:c + TILE][valid[r:r + TILE, c:c + TILE]]
                             for _, r, c in sel])
    pool_d = np.concatenate([during[r:r + TILE, c:c + TILE][valid[r:r + TILE, c:c + TILE]]
                             for _, r, c in sel])
    return float(threshold_otsu(pool_c)), float(threshold_otsu(pool_d)), len(sel)


def _worldcover_on(prof) -> np.ndarray:
    wc = np.zeros((prof["height"], prof["width"]), dtype="uint8")
    with rasterio.open(RAW / "worldcover" / "worldcover_2021_v200_domain.tif") as s:
        reproject(s.read(1), wc, src_transform=s.transform, src_crs=s.crs,
                  dst_transform=prof["transform"], dst_crs=prof["crs"],
                  resampling=Resampling.nearest)
    return wc


def detect() -> dict:
    from scipy import ndimage
    db = lambda a: 10 * np.log10(a)
    vv = {d: lee(_read_g(d, "VV")[0]) for d in (*PRE, DURING, POST)}
    _, prof = _read_g(DURING, "VV")
    ref = np.nanmean(np.stack([vv[d] for d in PRE]), axis=0)
    d_db, ref_db, dur_db, post_db = db(vv[DURING]), db(ref), db(vv[DURING]), db(vv[POST])
    change = d_db - ref_db
    valid = np.isfinite(change)
    wc = _worldcover_on(prof)

    t_change, t_water, ntiles = split_otsu(change, dur_db, valid & (wc != WC_BUILT))
    permanent = valid & ((wc == WC_WATER) | (ref_db <= t_water))
    built, trees = valid & (wc == WC_BUILT), valid & (wc == WC_TREES)
    observable = valid & ~permanent & ~built & ~trees & (wc != 0)    # 0: no land cover at the strip edges
    flood = observable & (change <= t_change) & (dur_db <= t_water)
    lab, n = ndimage.label(flood, structure=np.ones((3, 3)))
    sizes = ndimage.sum(flood, lab, np.arange(1, n + 1))
    flood &= np.isin(lab, np.flatnonzero(sizes >= MIN_PX) + 1)
    built_flag = built & (change >= DB_UP)

    cls = np.full(change.shape, NODATA, dtype="uint8")
    cls[observable] = DRY
    cls[flood] = FLOOD
    cls[permanent] = PERMANENT
    cls[built] = BUILT
    cls[built_flag] = BUILT_UP_FLAG
    cls[trees] = TREES
    p = prof | dict(dtype="uint8", nodata=NODATA, count=1)
    with rasterio.open(OUT / "e1_classes_10m.tif", "w", **p) as dst:
        dst.write(cls, 1)
    for name, arr in (("change_vv_db", change), ("during_vv_db", dur_db)):
        with rasterio.open(OUT / f"e1_{name}.tif", "w", **(prof | dict(dtype="float32"))) as dst:
            dst.write(arr.astype("float32"), 1)

    ha = lambda m: float(m.sum()) * RES * RES / 1e4
    still = flood & (post_db <= t_water)
    by_wc = {k: ha(flood & (wc == k)) for k in (20, 30, 40, 60, 90)}
    summary = dict(t_change_db=round(t_change, 2), t_water_db=round(t_water, 2), tiles=ntiles,
                   valid_ha=round(ha(valid)), observable_share=round(float(observable.sum() / valid.sum()), 3),
                   flood_ha=round(ha(flood)), flood_share_of_observable=round(float(flood.sum() / observable.sum()), 4),
                   still_dark_6aug_share=round(float(still.sum() / max(flood.sum(), 1)), 3),
                   builtup_brightening_ha=round(ha(built_flag)),
                   flood_ha_by_worldcover={str(k): round(v) for k, v in by_wc.items()})
    (ROOT / "outputs" / "tables").mkdir(parents=True, exist_ok=True)
    (ROOT / "outputs" / "tables" / "sar_e1_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


BASE_PRE, BASE_DURING = ("2025-06-29", "2025-07-11"), "2025-07-23"
RECURRING = 6            # 10 m class: E1 open water that the same test also flags in July 2025


def recurring() -> dict:
    """DESIGN D13: remove farmland that darkens every July. The E1 test, with the
    E1 thresholds and masks unchanged, is applied to the 2025 same-season scenes
    (same track and geometry; 23 Jul 2025 had 1.6 mm, ERA5). E1 open-water pixels
    it also flags become RECURRING and drop out of scoring, neither hit nor miss."""
    db = lambda a: 10 * np.log10(a)
    summ = json.loads((ROOT / "outputs" / "tables" / "sar_e1_summary.json").read_text())
    t_change, t_water = summ["t_change_db"], summ["t_water_db"]
    vv = {d: lee(_read_g(d, "VV")[0]) for d in (*BASE_PRE, BASE_DURING)}
    ref = np.nanmean(np.stack([vv[d] for d in BASE_PRE]), axis=0)
    change25, dur25 = db(vv[BASE_DURING]) - db(ref), db(vv[BASE_DURING])
    with rasterio.open(OUT / "e1_classes_10m.tif") as s:
        cls, prof = s.read(1), s.profile
    flood = cls == FLOOD
    rec_strict = flood & (change25 <= t_change) & (dur25 <= t_water)
    rec_loose = flood & (dur25 <= t_water)             # sensitivity: merely dark on 23 Jul 2025
    cls = cls.copy()
    cls[rec_strict] = RECURRING
    with rasterio.open(OUT / "e1_classes_10m.tif", "w", **prof) as dst:
        dst.write(cls, 1)
    ha = lambda m: float(m.sum()) * RES * RES / 1e4
    out = dict(e1_open_water_ha=round(ha(flood)), recurring_ha=round(ha(rec_strict)),
               recurring_share=round(float(rec_strict.sum() / flood.sum()), 3),
               loose_rule_dark_23jul2025_share=round(float(rec_loose.sum() / flood.sum()), 3),
               nonrecurring_ha=round(ha(flood & ~rec_strict)))
    summ["recurring_2025"] = out
    (ROOT / "outputs" / "tables" / "sar_e1_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(out, indent=2))
    return out


def to_model_grid() -> None:
    """10 m classes -> the 30 m model grid (DESIGN §5.4): per 30 m cell, the
    observable share and the flooded share of the observable part. A cell is
    scored if >= 50% observable, and counts as flooded if >= 50% of that is flood."""
    with rasterio.open(OUT / "e1_classes_10m.tif") as s:
        cls, prof = s.read(1), s.profile
    obs = np.where(cls == NODATA, np.nan, np.isin(cls, (DRY, FLOOD)).astype("float32"))
    fl = np.where(np.isin(cls, (DRY, FLOOD)), (cls == FLOOD).astype("float32"), np.nan)
    with rasterio.open(ROOT / "data" / "interim" / "dem_fabdem.tif") as g:
        gp = g.profile
    out = {}
    for name, arr in (("observable", obs), ("flooded", fl)):
        dst = np.full((gp["height"], gp["width"]), np.nan, dtype="float32")
        reproject(arr, dst, src_transform=prof["transform"], src_crs=prof["crs"],
                  dst_transform=gp["transform"], dst_crs=gp["crs"], src_nodata=np.nan,
                  dst_nodata=np.nan, resampling=Resampling.average)
        out[name] = dst
    scored = out["observable"] >= 0.5
    wet = scored & (out["flooded"] >= 0.5)
    obs30 = np.full(scored.shape, 255, dtype="uint8")
    obs30[np.isfinite(out["observable"])] = 0
    obs30[scored] = 1
    obs30[wet] = 2
    with rasterio.open(OUT / "e1_observed_30m.tif", "w",
                       **(gp | dict(dtype="uint8", nodata=255))) as dst:
        dst.write(obs30, 1)
    print(f"  e1_observed_30m.tif: {int(scored.sum())} scored cells, {int(wet.sum())} flooded "
          f"({wet.sum() / max(scored.sum(), 1):.1%})")


def places_summary(radius_m: float = 1500) -> None:
    """Per named locality, within radius: how much ground the radar could judge,
    how much of it turned to open water, and how built-up surfaces changed."""
    import csv
    from pyproj import Transformer
    with rasterio.open(OUT / "e1_classes_10m.tif") as s:
        cls, T = s.read(1), s.transform
    with rasterio.open(OUT / "e1_change_vv_db.tif") as s:
        ch = s.read(1)
    tr = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    places = json.loads((RAW / "places" / "nominatim_places.json").read_text())
    rows_i, cols_i = np.indices(cls.shape)
    xs, ys = T * (cols_i + 0.5, rows_i + 0.5)
    rows = []
    for name, hit in places.items():
        x, y = tr.transform(float(hit["lon"]), float(hit["lat"]))
        m = (xs - x) ** 2 + (ys - y) ** 2 <= radius_m ** 2
        c = cls[m]; v = c != NODATA
        if not m.any() or v.mean() < 0.2:
            continue                                   # outside the swath
        obs, b = np.isin(c, (DRY, FLOOD)), np.isin(c, (BUILT, BUILT_UP_FLAG))
        rows.append(dict(place=name, imaged_share=round(float(v.mean()), 2),
                         observable_share=round(float(obs.sum() / v.sum()), 2),
                         open_water_share_of_observable=round(float(np.mean(c[obs] == FLOOD)), 3) if obs.any() else "",
                         builtup_share=round(float(b.sum() / v.sum()), 2),
                         builtup_brightened_share=round(float(np.mean(c[b] == BUILT_UP_FLAG)), 3) if b.any() else "",
                         builtup_median_change_db=round(float(np.nanmedian(ch[m][b])), 2) if b.any() else "",
                         open_median_change_db=round(float(np.nanmedian(ch[m][obs])), 2) if obs.any() else ""))
    out = ROOT / "outputs" / "tables" / "sar_e1_places.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"  wrote {out.relative_to(ROOT)} ({len(rows)} localities in the swath)")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("dem", "all"):
        make_dem()
    if step == "rtc" and len(sys.argv) == 4:
        rtc(sys.argv[2], sys.argv[3])
    elif step in ("rtc", "all"):
        for d in scenes():
            for p in (POLS if d.startswith("2026") else ("VV",)):   # detection uses VV only
                rtc(d, p)
    if step in ("detect", "all"):
        detect()
        if (RAW / "s1" / "base2025_scenes.json").exists():
            recurring()
        to_model_grid()
        places_summary()
