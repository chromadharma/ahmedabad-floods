"""Terrain layers for M1 (HAND) and M2 (depressions), on both DEMs (DESIGN §5.1).

    python -m studies.ahmedabad.terrain grid        # warp GLO-30 and FABDEM to the 30 m UTM grid
    python -m studies.ahmedabad.terrain run         # depressions + HAND per DEM, tables
    python -m studies.ahmedabad.terrain all

Two conditionings, deliberately different (§5.1): HAND is computed on the
depression-filled DEM, so every cell drains; the depression layer is the
difference between that filled surface and the raw DEM, i.e. exactly what
HAND's conditioning throws away. pysheds fills rather than breaches, so the
HAND here follows Nobre et al. (2011) in using a filled DEM.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch import DOMAIN_BBOX, RAW  # noqa: E402

# pysheds 0.5 still calls np.in1d, removed in numpy 2.4. On the 1-D input it
# passes, np.isin is the documented drop-in.
if not hasattr(np, "in1d"):
    np.in1d = np.isin

INTERIM = ROOT / "data" / "interim"
TABLES = ROOT / "outputs" / "tables"
CRS = "EPSG:32643"          # UTM 43N
RES = 30.0
DEMS = {
    "glo30": sorted((RAW / "dem" / "glo30").glob("*.tif")),
    "fabdem": sorted((RAW / "dem" / "fabdem").glob("*.tif")),
}

MIN_DEPTH = 0.10            # m: a cell is "in a depression" if filling raises it by >= 10 cm


def grid_spec():
    W, S, E, N = transform_bounds("EPSG:4326", CRS, *DOMAIN_BBOX)
    W, S = np.floor(W / RES) * RES, np.floor(S / RES) * RES
    E, N = np.ceil(E / RES) * RES, np.ceil(N / RES) * RES
    w, h = int((E - W) / RES), int((N - S) / RES)
    return from_origin(W, N, RES, RES), w, h


def make_grid() -> None:
    transform, w, h = grid_spec()
    INTERIM.mkdir(parents=True, exist_ok=True)
    for name, tiles in DEMS.items():
        srcs = [rasterio.open(t) for t in tiles]
        mosaic, mtrans = merge(srcs)
        src_crs = srcs[0].crs
        for s in srcs:
            s.close()
        out = np.full((h, w), np.nan, dtype="float32")
        reproject(mosaic[0].astype("float32"), out, src_transform=mtrans, src_crs=src_crs,
                  dst_transform=transform, dst_crs=CRS, resampling=Resampling.bilinear,
                  src_nodata=-9999.0, dst_nodata=np.nan)
        prof = dict(driver="GTiff", width=w, height=h, count=1, dtype="float32", crs=CRS,
                    transform=transform, nodata=np.nan, compress="deflate", tiled=True)
        with rasterio.open(INTERIM / f"dem_{name}.tif", "w", **prof) as dst:
            dst.write(out, 1)
        print(f"  dem_{name}.tif  {w} x {h}  {np.nanmin(out):.1f}-{np.nanmax(out):.1f} m")


def _write(path: Path, arr, like: Path, dtype="float32", nodata=np.nan) -> None:
    with rasterio.open(like) as src:
        prof = src.profile | dict(dtype=dtype, nodata=nodata)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr.astype(dtype), 1)


def osm_drainage(kinds: tuple[str, ...]) -> np.ndarray:
    """OSM waterway lines of the given kinds, burned onto the grid (all touched cells)."""
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely.geometry import LineString
    transform, w, h = grid_spec()
    tr = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    ways = json.loads((RAW / "osm" / "waterways.json").read_text())["elements"]
    geoms = [LineString([tr.transform(p["lon"], p["lat"]) for p in el["geometry"]])
             for el in ways if el["tags"].get("waterway") in kinds and len(el["geometry"]) > 1]
    return rasterize(geoms, out_shape=(h, w), transform=transform, all_touched=True,
                     dtype="uint8").astype(bool)


# Natural drainage for the threshold check. Canals are engineered (the Narmada
# main canal and its branches) and water does not drain into them, so they are
# left out; so is Kharicut, an old irrigation canal now used as a storm drain.
CHECK_KINDS = ("river", "stream", "drain", "ditch")
SEED_KINDS = ("river",)                   # burned into HAND's drainage (catchments leave the domain)
THRESHOLDS_KM2 = (0.25, 0.5, 1, 2, 5, 10, 25, 50)
TOL_CELLS = 3                             # 90 m: a mapped channel counts as found within this


def stream_check(name: str, acc) -> float:
    """Recall of OSM natural drainage by the synthetic channel network, per
    threshold. OSM maps few streams here, so precision can't be scored; recall
    can. Rule: the coarsest threshold keeping >= 90% of the best recall."""
    from scipy import ndimage
    ref = osm_drainage(CHECK_KINDS)
    acc = np.asarray(acc)
    rows = []
    for t in THRESHOLDS_KM2:
        syn = acc >= t * 1e6 / (RES * RES)
        dist = ndimage.distance_transform_edt(~syn)
        rows.append(dict(dem=name, threshold_km2=t,
                         recall=round(float((dist[ref] <= TOL_CELLS).mean()), 3),
                         channel_km_per_km2=round(float(syn.sum()) * RES / 1e3
                                                  / (syn.size * RES * RES / 1e6), 2)))
    best = max(r["recall"] for r in rows)
    chosen = max(r["threshold_km2"] for r in rows if r["recall"] >= 0.9 * best)
    for r in rows:
        r["chosen"] = r["threshold_km2"] == chosen
    TABLES.mkdir(parents=True, exist_ok=True)
    out = TABLES / "stream_threshold_check.csv"
    mode = "a" if out.exists() and name != "fabdem" else "w"
    with open(out, mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if mode == "w":
            w.writeheader()
        w.writerows(rows)
    print(f"  {name} threshold check: " + ", ".join(
        f"{r['threshold_km2']}:{r['recall']:.2f}" for r in rows) + f" -> {chosen} km2")
    return chosen


def condition(name: str):
    from pysheds.grid import Grid
    path = INTERIM / f"dem_{name}.tif"
    grid = Grid.from_raster(str(path))
    dem = grid.read_raster(str(path))
    filled = grid.fill_depressions(grid.fill_pits(dem))
    fdir = grid.flowdir(grid.resolve_flats(filled))
    acc = grid.accumulation(fdir)
    return grid, dem, filled, fdir, acc


def hand(name: str, grid, filled, fdir, acc, threshold_km2: float) -> None:
    path = INTERIM / f"dem_{name}.tif"
    streams = acc >= threshold_km2 * 1e6 / (RES * RES)    # stays a pysheds Raster
    streams[osm_drainage(SEED_KINDS)] = True
    h = np.asarray(grid.compute_hand(fdir, filled, streams), dtype="float32")
    _write(INTERIM / f"hand_{name}.tif", h, path)
    _write(INTERIM / f"streams_{name}.tif", np.asarray(streams), path, dtype="uint8", nodata=0)
    print(f"  {name}: HAND on {threshold_km2} km2 channels + OSM rivers; "
          f"median {np.nanmedian(h):.1f} m")


def depressions(name: str, dem, filled) -> dict:
    from scipy import ndimage

    path = INTERIM / f"dem_{name}.tif"
    depth = np.asarray(filled) - np.asarray(dem)
    depth[depth < 0] = 0

    # connected depressions, 8-neighbour
    lab, n = ndimage.label(depth >= MIN_DEPTH, structure=np.ones((3, 3)))
    idx = np.arange(1, n + 1)
    cells = ndimage.sum(np.ones_like(depth), lab, idx)
    vol = ndimage.sum(depth, lab, idx) * RES * RES
    dmax = ndimage.maximum(depth, lab, idx)
    _write(INTERIM / f"depdepth_{name}.tif", depth, path)
    _write(INTERIM / f"deplabel_{name}.tif", lab, path, dtype="int32", nodata=0)

    order = np.argsort(-vol)
    rows = []
    with rasterio.open(path) as src:
        T = src.transform
    com = ndimage.center_of_mass(np.ones_like(depth), lab, idx[order[:40]])
    for k, (r, c) in zip(order[:40], com):
        x, y = T * (c + 0.5, r + 0.5)
        rows.append(dict(id=int(idx[k]), area_ha=round(cells[k] * RES * RES / 1e4, 1),
                         volume_m3=int(vol[k]), max_depth_m=round(float(dmax[k]), 2),
                         x_utm=round(x), y_utm=round(y)))
    TABLES.mkdir(parents=True, exist_ok=True)
    with open(TABLES / f"depressions_{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    share = float((depth >= MIN_DEPTH).mean())
    print(f"  {name}: {n} depressions >= {MIN_DEPTH} m, {share:.1%} of cells")
    return dict(n=n, share=share)


def run() -> None:
    """Threshold chosen on FABDEM (bare earth) and applied to both DEMs, so the
    DEM comparison isn't confounded by different channel networks."""
    conditioned = {n: condition(n) for n in ("fabdem", "glo30")}
    chosen = None
    for n, (grid, dem, filled, fdir, acc) in conditioned.items():
        depressions(n, dem, filled)
        c = stream_check(n, acc)
        chosen = chosen or c
    for n, (grid, dem, filled, fdir, acc) in conditioned.items():
        hand(n, grid, filled, fdir, acc, chosen)


def places_table() -> None:
    """Each named locality: elevation, depression depth/size and HAND on both DEMs."""
    from pyproj import Transformer
    places = json.loads((RAW / "places" / "nominatim_places.json").read_text())
    tr = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    rows = []
    for pname, hit in places.items():
        if not hit:
            continue
        x, y = tr.transform(float(hit["lon"]), float(hit["lat"]))
        row = dict(place=pname, osm_type=hit.get("addresstype"), lon=round(float(hit["lon"]), 4),
                   lat=round(float(hit["lat"]), 4))
        for name in DEMS:
            def sample(stem, dtype=float):
                with rasterio.open(INTERIM / f"{stem}_{name}.tif") as s:
                    return dtype(next(s.sample([(x, y)]))[0])
            lab = sample("deplabel", int)
            area = ""
            if lab:
                with rasterio.open(INTERIM / f"deplabel_{name}.tif") as s:
                    area = round(float((s.read(1) == lab).sum()) * RES * RES / 1e4, 1)
            row |= {f"elev_{name}": round(sample("dem"), 1),
                    f"dep_depth_{name}": round(sample("depdepth"), 2),
                    f"dep_area_ha_{name}": area,
                    f"hand_{name}": round(sample("hand"), 1)}
        rows.append(row)
    with open(TABLES / "places_terrain.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"  wrote {TABLES.relative_to(ROOT) / 'places_terrain.csv'}")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("grid", "all"):
        make_grid()
    if step in ("run", "all"):
        run()
        places_table()
