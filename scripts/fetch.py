"""Fetch the raw data for event E1 (23-25 Jul 2026) into data/raw/.
Every source, URL and licence is listed in data/README.md.

    python scripts/fetch.py dem          # Copernicus GLO-30, 2 tiles (~90 MB)
    python scripts/fetch.py fabdem       # FABDEM v1-2, 2 tiles cut from the 1.9 GB zip by byte range (~29 MB)
    python scripts/fetch.py wards        # DataMeet Ahmedabad wards, pinned commit (1.2 MB)
    python scripts/fetch.py press        # snapshots of the pages the rain and river figures come from
    python scripts/fetch.py s1           # Sentinel-1 track-B scenes, city window only (needs `make env`)
    python scripts/fetch.py s1 --plan    # list the scenes and estimate the bytes; download nothing
    python scripts/fetch.py era5         # ERA5 hourly rain, 9 grid cells over the domain (Open-Meteo)
    python scripts/fetch.py places       # OSM Nominatim points for the localities the reports name
    python scripts/fetch.py waterways    # OSM waterway lines over the domain (Overpass)
    python scripts/fetch.py all

Every group except s1 is standard library only, so it runs before the
environment exists. Files already present with the expected size are skipped.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
UA = {"User-Agent": "ahmedabad-floods/0.1 (research)"}

# W, S, E, N. AMC extent (72.45-72.70 E, 22.91-23.14 N; DESIGN §4) plus ~5-10 km,
# so the SAR window also covers the ring the model domain buffers into.
DOMAIN_BBOX = (72.35, 22.85, 72.80, 23.20)

FILES = {
    "dem": {   # Copernicus GLO-30 DSM, Cloud-Optimised GeoTIFFs on AWS Open Data
        f"dem/glo30/{t}.tif":
            f"https://copernicus-dem-30m.s3.amazonaws.com/{t}/{t}.tif"
        for t in ("Copernicus_DSM_COG_10_N22_00_E072_00_DEM",
                  "Copernicus_DSM_COG_10_N23_00_E072_00_DEM")
    },
    "wards": {   # last commit touching the file (2016-08-12): pre-2020 AMC limits
        "wards/datameet_ahmedabad_wards.geojson":
            "https://raw.githubusercontent.com/datameet/Municipal_Spatial_Data/"
            "46679b9c173e4f13745974134c3802f92d80bf8f/Ahmedabad/Wards.geojson",
    },
}

FABDEM_ZIP = ("https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/"
              "N20E070-N30E080_FABDEM_V1-2.zip")
FABDEM_TILES = ("N22E072_FABDEM_V1-2.tif", "N23E072_FABDEM_V1-2.tif")

# Pages the E1 rain-gauge and Vasna-barrage figures are transcribed from
# (DESIGN §1, §3). Kept so every transcribed number can be checked against
# the page as it stood when fetched.
PRESS = {
    "deshgujarat_2026-07-23_11-inches.html":
        "https://deshgujarat.com/2026/07/23/ahmedabad-city-records-over-11-inches-of-rain-in-12-hours-area-wise-rainfall-data-here/",
    "deshgujarat_2026-07-23_ward-wise.html":
        "https://deshgujarat.com/2026/07/23/where-did-it-rain-in-ahmedabad-city-ward-wise-rainfall-data-here/",
    "deshgujarat_2026-07-25_ward-wise-24h.html":
        "https://deshgujarat.com/2026/07/25/ahmedabad-city-records-upto-3-7-inches-rain-in-24-hours-ward-wise-rainfall-data-here/",
    "deshgujarat_2026-07-25_societies-cleared.html":
        "https://deshgujarat.com/2026/07/25/rainwater-cleared-from-107-of-126-waterlogged-societies-in-ahmedabad-amc/",
    "counterview_2026-08_sabarmati-riverfront.html":
        "https://www.counterview.net/2026/08/did-sabarmati-riverfront-make-ahmedabad.html",
    "gujaratsamachar_amc-waterlogging-spots.html":
        "https://english.gujaratsamachar.com/news/ahmedabad/ahmedabad-deluged-over-8-inches-of-rain-exposes-amcs-multi-crore-pre-monsoon-claims-as-posh-belts-submerge-73506814338",
}

# E1 track B (≈01:09 UTC, descending, S1D; DESIGN §4): pre, pre, during, post.
# Change detection pairs images from the same track only.
S1_BUCKET = "https://sentinel-s1-l1c.s3.amazonaws.com"
S1_DATES = ("2026-07-01", "2026-07-13", "2026-07-25", "2026-08-06")
S1_MISSION = "S1D"
S1_HOUR_UTC = "01"          # descending passes; the evening ascending pass is ~13 UTC
S1_POLS = ("vv", "vh")
S1_LIMIT_BYTES = 1e9        # DESIGN D4: stop and ask if the real figure passes 1 GB
BLOCK = 1024                # the GRD TIFFs are tiled 1024 x 1024, deflate


# ---------------------------------------------------------------- plain HTTP

def _get(url: str, dest: Path, headers: dict | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        size = int(r.headers.get("Content-Length") or 0)
        if dest.exists() and size and dest.stat().st_size == size:
            print(f"  have {dest.relative_to(RAW)}")
            return
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    print(f"  got  {dest.relative_to(RAW)} ({dest.stat().st_size/1e6:.1f} MB)")


def _range(url: str, start: int, length: int) -> urllib.request.addinfourl:
    req = urllib.request.Request(
        url, headers={**UA, "Range": f"bytes={start}-{start + length - 1}"})
    r = urllib.request.urlopen(req, timeout=300)
    if r.status != 206:
        raise RuntimeError(f"{url}: server ignored the Range header (HTTP {r.status})")
    return r


# ------------------------------------------------------ FABDEM out of the zip

class _HTTPFile:
    """Seekable read-only view of a remote file, one Range request per read.
    Enough for zipfile to parse the central directory at the end of the zip."""

    def __init__(self, url: str):
        self.url, self.pos = url, 0
        head = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(head, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = (off, self.pos + off, self.size + off)[whence]
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n < 0 else min(n, self.size - self.pos)
        if n <= 0:
            return b""
        with _range(self.url, self.pos, n) as r:
            b = r.read()
        self.pos += len(b)
        return b


def fetch_fabdem() -> None:
    import zipfile
    todo = [t for t in FABDEM_TILES if not (RAW / "dem/fabdem" / t).exists()]
    for t in set(FABDEM_TILES) - set(todo):
        print(f"  have dem/fabdem/{t}")
    if not todo:
        return
    zf = zipfile.ZipFile(_HTTPFile(FABDEM_ZIP))
    for name in todo:
        zi = zf.getinfo(name)
        with _range(FABDEM_ZIP, zi.header_offset, 30) as r:
            local = r.read()
        n_name, n_extra = struct.unpack("<HH", local[26:30])
        start = zi.header_offset + 30 + n_name + n_extra
        if zi.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise RuntimeError(f"{name}: unsupported compression {zi.compress_type}")
        inflate = zlib.decompressobj(-15) if zi.compress_type == zipfile.ZIP_DEFLATED else None
        dest = RAW / "dem/fabdem" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp, crc = dest.with_suffix(".tif.part"), 0
        with _range(FABDEM_ZIP, start, zi.compress_size) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                out = inflate.decompress(chunk) if inflate else chunk
                crc = zlib.crc32(out, crc)
                f.write(out)
        if crc != zi.CRC or tmp.stat().st_size != zi.file_size:
            raise RuntimeError(f"{name}: CRC or size mismatch; partial file left at {tmp}")
        tmp.replace(dest)
        print(f"  got  dem/fabdem/{name} ({zi.file_size/1e6:.1f} MB)")


# --------------------------------------------------------------------- press

def fetch_press() -> None:
    for fname, url in PRESS.items():
        dest = RAW / "press" / fname
        if dest.exists():
            print(f"  have press/{fname}")
            continue
        try:
            _get(url, dest)
        except urllib.error.URLError as e:     # one dead page shouldn't stop the rest
            print(f"  FAIL press/{fname}: {e}")
    (RAW / "press" / "SOURCES.json").write_text(json.dumps(PRESS, indent=2))


# -------------------------------------------------------------------- places

# Localities named in the E1 reports (press/), for map labels and first-look
# checks. Nominatim usage policy: identify, <= 1 request/s, cache results.
PLACES = ("Bopal", "Ghuma", "Shela", "Vejalpur", "Sarkhej", "Makarba", "Jodhpur",
          "Bodakdev", "Thaltej", "Gota", "Vasna", "Paldi", "Maninagar", "Naroda",
          "Kalupur", "Asarwa")


def fetch_places() -> None:
    import time
    import urllib.parse
    dest = RAW / "places" / "nominatim_places.json"
    if dest.exists():
        print(f"  have {dest.relative_to(RAW)}")
        return
    W, S, E, N = DOMAIN_BBOX
    out = {}
    for name in PLACES:
        q = urllib.parse.urlencode({"q": f"{name}, Ahmedabad", "format": "jsonv2", "limit": 1,
                                    "viewbox": f"{W},{N},{E},{S}", "bounded": 1})
        with urllib.request.urlopen(urllib.request.Request(
                "https://nominatim.openstreetmap.org/search?" + q, headers=UA), timeout=60) as r:
            hits = json.load(r)
        out[name] = hits[0] if hits else None
        print(f"  {name}: " + (f"{float(hits[0]['lat']):.4f}, {float(hits[0]['lon']):.4f} "
                               f"({hits[0].get('addresstype')})" if hits else "NOT FOUND"))
        time.sleep(1.1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1))


# ---------------------------------------------------------------- waterways

# OSM waterway lines, to check the HAND drainage threshold against and to seed
# the Sabarmati, whose catchment lies mostly outside the domain (DESIGN §5.2).
# Direct Overpass call with the project UA and no osmnx Referer, a retry cap,
# and rotation across backends (the traps recorded for Project 1).
OVERPASS = ("https://gall.openstreetmap.de/api", "https://lambert.openstreetmap.de/api",
            "https://overpass-api.de/api")


def fetch_waterways() -> None:
    import time
    import urllib.parse
    dest = RAW / "osm" / "waterways.json"
    if dest.exists():
        print(f"  have {dest.relative_to(RAW)}")
        return
    W, S, E, N = DOMAIN_BBOX
    query = (f'[out:json][timeout:180];way["waterway"~"^(river|stream|canal|drain|ditch)$"]'
             f"({S},{W},{N},{E});out tags geom;")
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for base in OVERPASS:
        for attempt in range(2):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        base + "/interpreter", data=body, headers=UA), timeout=240) as r:
                    data = json.load(r)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(data))
                kinds = {}
                for el in data["elements"]:
                    k = el["tags"].get("waterway"); kinds[k] = kinds.get(k, 0) + 1
                print(f"  got  {dest.relative_to(RAW)} from {base}: {kinds}")
                return
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                print(f"    {base} attempt {attempt + 1}: {e}")
                time.sleep(15)
    raise RuntimeError(f"all Overpass backends failed: {last}")


# ---------------------------------------------------------------------- ERA5

# ERA5 hourly precipitation via Open-Meteo's archive API (no key). Only used to
# say whether it rained before each S1 pass: at 0.25° it is far too coarse,
# and too smooth, to force the models. The 3 x 3 native grid cells cover the domain.
ERA5_LATS = (22.75, 23.00, 23.25)
ERA5_LONS = (72.25, 72.50, 72.75)
ERA5_PERIOD = ("2026-06-25", "2026-08-07")


def fetch_era5() -> None:
    import urllib.parse
    dest = RAW / "era5" / f"era5_hourly_precip_{ERA5_PERIOD[0]}_{ERA5_PERIOD[1]}.json"
    if dest.exists():
        print(f"  have {dest.relative_to(RAW)}")
        return
    pts = [(la, lo) for la in ERA5_LATS for lo in ERA5_LONS]
    q = urllib.parse.urlencode({
        "latitude": ",".join(str(p[0]) for p in pts),
        "longitude": ",".join(str(p[1]) for p in pts),
        "start_date": ERA5_PERIOD[0], "end_date": ERA5_PERIOD[1],
        "hourly": "precipitation", "timezone": "UTC", "models": "era5"})
    with urllib.request.urlopen(urllib.request.Request(
            "https://archive-api.open-meteo.com/v1/archive?" + q, headers=UA), timeout=120) as r:
        data = json.load(r)
    if any(v is None for d in data for v in d["hourly"]["precipitation"]):
        raise RuntimeError("ERA5 series has gaps; the archive may not reach the end date yet")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data))
    print(f"  got  {dest.relative_to(RAW)} ({len(data)} cells)")


# --------------------------------------------------------------- Sentinel-1

def _s3_prefixes(prefix: str) -> list[str]:
    """Anonymous ListObjectsV2 on the S1 bucket: the scene folders under prefix."""
    import xml.etree.ElementTree as ET
    url = f"{S1_BUCKET}/?list-type=2&delimiter=/&prefix={prefix}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        root = ET.fromstring(r.read())
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    if root.findtext("s3:IsTruncated", namespaces=ns) == "true":
        raise RuntimeError(f"listing truncated for {prefix}; narrow the prefix")
    return [p.text for p in root.findall("s3:CommonPrefixes/s3:Prefix", ns)]


def select_scenes(infos: list[dict], bbox=DOMAIN_BBOX) -> list[dict]:
    """productInfo.json records whose footprint touches bbox."""
    from shapely.geometry import box, shape
    area = box(*bbox)
    return [i for i in infos if shape(i["footprint"]).intersects(area)]


def pixel_window(transformer, bbox, shape, pad=512, block=BLOCK):
    """Row/col window of bbox in a GRD image, padded and snapped to whole tiles.
    transformer: anything with rowcol(xs, ys) in image space (a GCPTransformer).
    Returns (row0, row1, col0, col1), half-open, or None if bbox misses the image."""
    W, S, E, N = bbox
    k = 11
    xs = [W + (E - W) * i / (k - 1) for i in range(k)]
    ys = [S + (N - S) * i / (k - 1) for i in range(k)]
    px = xs + xs + [W] * k + [E] * k          # points along all four edges
    py = [S] * k + [N] * k + ys + ys
    rows, cols = transformer.rowcol(px, py)
    rows, cols = [int(r) for r in rows], [int(c) for c in cols]   # numpy ints won't serialise
    h, w = shape
    r0, r1 = max(0, min(rows) - pad), min(h, max(rows) + pad + 1)
    c0, c1 = max(0, min(cols) - pad), min(w, max(cols) + pad + 1)
    if r0 >= r1 or c0 >= c1:
        return None
    snap = lambda lo, hi, n: (lo // block * block, min(n, math.ceil(hi / block) * block))
    (r0, r1), (c0, c1) = snap(r0, r1, h), snap(c0, c1, w)
    return r0, r1, c0, c1


def _s1_plan() -> list[dict]:
    """Scenes to fetch, each with its measurement windows and compressed byte count."""
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
    import rasterio
    from rasterio.transform import GCPTransformer

    plan = []
    for date in S1_DATES:
        y, m, d = date.split("-")
        stamp = f"{y}{m}{d}T{S1_HOUR_UTC}"
        prefix = f"GRD/{y}/{int(m)}/{int(d)}/IW/DV/{S1_MISSION}_IW_GRDH_1SDV_{stamp}"
        infos = []
        for p in _s3_prefixes(prefix):
            with urllib.request.urlopen(urllib.request.Request(
                    f"{S1_BUCKET}/{p}productInfo.json", headers=UA), timeout=60) as r:
                infos.append(json.load(r))
        hits = select_scenes(infos)
        if not hits:
            raise RuntimeError(f"{date}: no {S1_MISSION} slice at {S1_HOUR_UTC}h UTC covers the domain")
        if len({i["missionDataTakeId"] for i in hits}) > 1:
            raise RuntimeError(f"{date}: slices from more than one datatake; check the track")
        for info in hits:
            fmap = info["filenameMap"]       # original SAFE path -> short S3 name
            meas = {}
            for pol in S1_POLS:
                (orig, short), = [(o, s) for o, s in fmap.items()
                                  if s == f"measurement/iw-{pol}.tiff"]
                url = f"{S1_BUCKET}/{info['path']}/{short}"
                with rasterio.open(f"/vsicurl/{url}") as src:
                    if src.block_shapes[0] != (BLOCK, BLOCK):
                        raise RuntimeError(f"{info['id']} {pol}: tiles are "
                                           f"{src.block_shapes[0]}, expected {BLOCK}")
                    win = pixel_window(GCPTransformer(src.gcps[0]), DOMAIN_BBOX,
                                       (src.height, src.width))
                    if win is None:
                        continue
                    r0, r1, c0, c1 = win
                    nbytes = sum(src.block_size(1, i, j)
                                 for i in range(r0 // BLOCK, math.ceil(r1 / BLOCK))
                                 for j in range(c0 // BLOCK, math.ceil(c1 / BLOCK)))
                meas[pol] = {"orig": orig, "url": url, "window": win, "bytes": nbytes}
            if meas:
                plan.append({"date": date, "id": info["id"], "path": info["path"],
                             "footprint": info["footprint"], "files": fmap,
                             "measurement": meas})
    return plan


def _write_window(url: str, dest: Path, win) -> None:
    """Full-size sparse copy of a GRD TIFF holding only the tiles in win.
    Keeping the full shape keeps the SAFE product consistent with its
    annotation XML, so calibration and terrain correction read it as usual."""
    import rasterio
    from rasterio.windows import Window
    r0, r1, c0, c1 = win
    tmp = dest.with_suffix(".tiff.part")
    with rasterio.open(f"/vsicurl/{url}") as src:
        gcps, crs = src.gcps
        prof = dict(driver="GTiff", width=src.width, height=src.height, count=1,
                    dtype=src.dtypes[0], tiled=True, blockxsize=BLOCK, blockysize=BLOCK,
                    compress="deflate", sparse_ok=True, gcps=gcps, crs=crs)
        with rasterio.open(tmp, "w", **prof) as dst:
            for r in range(r0, r1, BLOCK):        # one tile row per request batch
                w = Window(c0, r, c1 - c0, min(BLOCK, r1 - r))
                dst.write(src.read(1, window=w), 1, window=w)
    tmp.replace(dest)


def fetch_s1(plan_only: bool = False) -> None:
    plan = _s1_plan()
    total = sum(m["bytes"] for s in plan for m in s["measurement"].values())
    for s in plan:
        for pol, m in s["measurement"].items():
            r0, r1, c0, c1 = m["window"]
            print(f"  {s['date']} {s['id'][-38:]} {pol}: rows {r0}-{r1} cols {c0}-{c1}"
                  f"  {m['bytes']/1e6:6.1f} MB")
    print(f"  total image bytes: {total/1e6:.0f} MB for {len(plan)} scene(s)")
    if plan_only:
        return
    if total > S1_LIMIT_BYTES:
        raise SystemExit(f"S1 window totals {total/1e9:.2f} GB, over the "
                         f"{S1_LIMIT_BYTES/1e9:.0f} GB agreed in DESIGN D4. Stopping.")
    for s in plan:
        safe = RAW / "s1" / f"{s['id']}.SAFE"
        done = safe / "fetch_window.json"
        if done.exists():
            print(f"  have s1/{safe.name}")
            continue
        for orig, short in s["files"].items():
            if short.startswith("measurement/"):
                continue
            _get(f"{S1_BUCKET}/{s['path']}/{short}", safe / orig)
        for pol, m in s["measurement"].items():
            dest = safe / m["orig"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_window(m["url"], dest, m["window"])
            print(f"  got  s1/{safe.name}/{m['orig']} (window, {m['bytes']/1e6:.0f} MB read)")
        done.write_text(json.dumps(
            {"date": s["date"], "bbox": DOMAIN_BBOX,
             "measurement": {p: {"window_rows_cols": m["window"], "bytes_read": m["bytes"]}
                             for p, m in s["measurement"].items()}}, indent=2))
    (RAW / "s1" / "e1_scenes.json").write_text(json.dumps(
        [{k: s[k] for k in ("date", "id", "footprint")} for s in plan], indent=2))


# ---------------------------------------------------------------------- main

GROUPS = ("dem", "fabdem", "wards", "press", "places", "waterways", "era5", "s1")


def main(which: str, plan_only: bool = False) -> None:
    for grp in GROUPS if which == "all" else (which,):
        print(f"[{grp}]")
        if grp in FILES:
            for rel, url in FILES[grp].items():
                _get(url, RAW / rel)
        elif grp == "fabdem":
            fetch_fabdem()
        elif grp == "press":
            fetch_press()
        elif grp == "waterways":
            fetch_waterways()
        elif grp == "places":
            fetch_places()
        elif grp == "era5":
            fetch_era5()
        elif grp == "s1":
            fetch_s1(plan_only)
        else:
            raise SystemExit(f"unknown group {grp!r}; one of {', '.join(GROUPS)}, all")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "all", plan_only="--plan" in sys.argv)
