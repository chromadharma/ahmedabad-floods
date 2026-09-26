"""Rain before each E1 Sentinel-1 pass, from ERA5 hourly (fetch.py era5).

Answers two questions from DESIGN §4: did it rain before the 13 July
reference image (if so, 1 July stands alone), and how long after the last
rain was the 25 July image taken. ERA5 at 0.25° smooths convective rain,
so this is evidence of whether it rained, not of how much fell locally.

    python scripts/rain_check.py     # -> outputs/tables/s1_antecedent_rain.csv
"""
from __future__ import annotations

import csv
import glob
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs" / "tables" / "s1_antecedent_rain.csv"
WET_MM_H = 1.0                   # an hour "with rain" for the since-last-rain count
WINDOWS_H = (6, 24, 48, 72)


def passes() -> list[tuple[str, datetime]]:
    """(date, mid-slice UTC time) per scene, from the scene IDs fetch.py chose."""
    out = []
    for s in json.loads((RAW / "s1" / "e1_scenes.json").read_text()):
        start, stop = (datetime.strptime(t, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                       for t in s["id"].split("_")[4:6])
        out.append((s["date"], start + (stop - start) / 2))
    return out


def main() -> None:
    cells = json.loads(Path(glob.glob(str(RAW / "era5" / "era5_hourly_precip_*.json"))[0]).read_text())
    rows = []
    for date, t in passes():
        for c in cells:
            times = [datetime.fromisoformat(x).replace(tzinfo=timezone.utc)
                     for x in c["hourly"]["time"]]
            # ERA5 hourly precipitation is the total over the hour ENDING at the stamp
            series = [(ts, mm) for ts, mm in zip(times, c["hourly"]["precipitation"]) if ts <= t]
            row = {"date": date, "pass_utc": t.strftime("%Y-%m-%d %H:%M"),
                   "lat": c["latitude"], "lon": c["longitude"]}
            for h in WINDOWS_H:
                row[f"rain_{h}h_mm"] = round(sum(mm for ts, mm in series
                                                 if ts > t - timedelta(hours=h)), 1)
            wet = [ts for ts, mm in series if mm >= WET_MM_H]
            row["hours_since_rain_ge1mm"] = (round((t - wet[-1]).total_seconds() / 3600, 1)
                                             if wet else "")
            rows.append(row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT.relative_to(ROOT)}")
    for date, _ in passes():
        sel = [r for r in rows if r["date"] == date]
        since = [r["hours_since_rain_ge1mm"] for r in sel if r["hours_since_rain_ge1mm"] != ""]
        print(f"  {date}: 24 h max {max(r['rain_24h_mm'] for r in sel):5.1f} mm, "
              f"72 h max {max(r['rain_72h_mm'] for r in sel):6.1f} mm, "
              f"last hour >= {WET_MM_H} mm: {min(since) if since else 'none in record'} h before")


if __name__ == "__main__":
    main()
