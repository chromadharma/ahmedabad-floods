"""Geocode the reported flood locations (DESIGN D13, built-up score).

    python -m studies.ahmedabad.reports

Input: data/manual/reported_locations_2026-07.csv (transcribed from the press
snapshots, one row per reported place). Points are matched to OSM features by
name, preferring the right kind of feature (a bus stop for a BRTS station, a
below-grade road for an underpass). Matches that are ambiguous (several
candidates more than 1 km apart) or missing are flagged, never guessed.
Localities go through Nominatim and are kept for context, not scored as points.

Output: outputs/tables/reported_locations_geocoded.csv (+ .geojson).
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch import DOMAIN_BBOX, RAW, UA  # noqa: E402

IN = ROOT / "data" / "manual" / "reported_locations_2026-07.csv"
OUT = ROOT / "outputs" / "tables" / "reported_locations_geocoded"
AMBIGUOUS_M = 1000


def _kind_ok(kind: str, tags: dict) -> bool:
    if kind in ("brts_station", "brts_corridor"):
        return (tags.get("highway") == "bus_stop" or tags.get("amenity") == "bus_station"
                or tags.get("public_transport") in ("station", "platform"))
    if kind == "underpass":
        return "highway" in tags and ("tunnel" in tags or tags.get("layer", "").startswith("-")
                                      or "underpass" in tags.get("name", "").lower())
    if kind == "residential":
        return tags.get("landuse") == "residential" or "building" in tags
    return True


def _dist_m(a, b) -> float:
    dy = (a[1] - b[1]) * 111_320
    dx = (a[0] - b[0]) * 111_320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(dx, dy)


def _nominatim(q: str):
    W, S, E, N = DOMAIN_BBOX
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": f"{q}, Ahmedabad", "format": "jsonv2", "limit": 1,
         "viewbox": f"{W},{N},{E},{S}", "bounded": 1})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        hits = json.load(r)
    time.sleep(1.1)
    return hits[0] if hits else None


NEAR_M = 3000       # a point must lie within this of the locality its source names


def _variants(r) -> list[str]:
    q = r["osm_query"]
    if r["kind"] in ("brts_station", "brts_corridor"):
        return [q, f"{q} BRTS"]
    if r["kind"] == "underpass":
        return [f"{q} underpass", q]
    return [q, r["reported_as"]]


def main() -> None:
    feats = json.loads((RAW / "osm" / "features.json").read_text())["elements"]
    rows = list(csv.DictReader(open(IN, encoding="utf-8")))
    near_cache: dict[str, tuple | None] = {}

    def near_pt(name):
        if name and name not in near_cache:
            h = _nominatim(name)
            near_cache[name] = (float(h["lon"]), float(h["lat"])) if h else None
        return near_cache.get(name)

    out = []
    for r in rows:
        q = r["osm_query"].lower()
        res = dict(r, match="", osm_id="", lon="", lat="", method="", flag="")
        if r["kind"] == "local_account":
            res["flag"] = "unscored: no published source yet"
            out.append(res); continue
        npt = near_pt(r.get("near", ""))
        ok_near = lambda lon, lat: npt is None or _dist_m((lon, lat), npt) <= NEAR_M
        if r["precision"] in ("point", "street"):
            cands = []
            for e in feats:
                t = e.get("tags", {})
                c = e.get("center") or {"lon": e.get("lon"), "lat": e.get("lat")}
                if (q in t.get("name", "").lower() and _kind_ok(r["kind"], t)
                        and ok_near(c["lon"], c["lat"])):
                    cands.append((t["name"], f"{e['type']}/{e['id']}", c["lon"], c["lat"]))
            if cands:
                spread = max(_dist_m(a[2:], b[2:]) for a in cands for b in cands)
                name, oid, lon, lat = cands[0]
                if spread > AMBIGUOUS_M:
                    res["flag"] = (f"ambiguous: {len(cands)} OSM candidates up to {spread/1000:.1f} km apart: "
                                   + "; ".join(sorted({c[0] for c in cands}))[:200])
                else:   # candidates are parts of one feature: use their mean
                    lon = sum(c[2] for c in cands) / len(cands); lat = sum(c[3] for c in cands) / len(cands)
                res.update(match=name, osm_id=oid, lon=round(lon, 5), lat=round(lat, 5), method="osm name+kind")
                out.append(res); continue
            for v in _variants(r):
                hit = _nominatim(v)
                if hit and hit.get("addresstype") not in ("suburb", "neighbourhood", "city", "town", "village",
                                                          "quarter", "city_district", "county", "state_district")                         and ok_near(float(hit["lon"]), float(hit["lat"])):
                    res.update(match=hit.get("display_name", "")[:80], osm_id=f"{hit['osm_type']}/{hit['osm_id']}",
                               lon=round(float(hit["lon"]), 5), lat=round(float(hit["lat"]), 5), method="nominatim",
                               flag="check: point matched by Nominatim, not by OSM feature")
                    break
            if res["lon"] == "" and npt:
                res.update(lon=round(npt[0], 5), lat=round(npt[1], 5), method="source locality",
                           precision="locality", flag="degraded to locality: point not found")
            elif res["lon"] == "":
                res["flag"] = "unmatched"
            out.append(res); continue
        hit = _nominatim(r["osm_query"])
        if hit:
            res.update(match=hit.get("display_name", "")[:80], osm_id=f"{hit['osm_type']}/{hit['osm_id']}",
                       lon=round(float(hit["lon"]), 5), lat=round(float(hit["lat"]), 5), method="nominatim")
        else:
            res["flag"] = "unmatched"
        out.append(res)
    # analyst review of flagged matches (data/manual/reported_locations_review.csv)
    review = {r["rid"]: r for r in csv.DictReader(open(IN.with_name("reported_locations_review.csv"),
                                                         encoding="utf-8"))}
    for r in out:
        d = review.get(r["rid"])
        if not d:
            continue
        if d["decision"] == "accept":
            r["flag"] = ""
        elif d["decision"].startswith("degrade:"):
            r["precision"], r["flag"] = d["decision"].split(":")[1], ""
        elif d["decision"] == "reject":
            r.update(lon="", lat="", match="", osm_id="", flag="unmatched (match rejected in review)")
        r["review"] = f"{d['decision']}: {d['reason']}"
    for r in out:
        r.setdefault("review", "")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    fc = dict(type="FeatureCollection", features=[
        dict(type="Feature", geometry=dict(type="Point", coordinates=[r["lon"], r["lat"]]),
             properties={k: v for k, v in r.items() if k not in ("lon", "lat")})
        for r in out if r["lon"] != ""])
    OUT.with_suffix(".geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in out if r["lon"] != "" and not r["flag"])
    print(f"  {len(out)} reports: {ok} clean matches, "
          f"{sum(1 for r in out if r['flag'].startswith('ambiguous'))} ambiguous, "
          f"{sum(1 for r in out if r['flag'].startswith('check'))} Nominatim points to check, "
          f"{sum(1 for r in out if r['flag'].startswith('degraded'))} degraded to locality, "
          f"{sum(1 for r in out if r['flag'].startswith('unmatched'))} unmatched")


if __name__ == "__main__":
    main()
