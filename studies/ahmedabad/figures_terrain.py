"""Terrain figures (house style: viz/viz_theme.py).

    python -m studies.ahmedabad.figures_terrain dem_effect   # GLO-30 vs FABDEM depressions
    python -m studies.ahmedabad.figures_terrain west         # FABDEM depressions + HAND, named localities
    python -m studies.ahmedabad.figures_terrain all

Colour logic in both: yellow = wetter (a deeper depression, or ground nearer
to drainage), on a light hillshade of the bare-earth DEM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LightSource, Normalize
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from viz.viz_theme import (FONT_BOLD, FONT_SEMIBOLD, MUTED, TEXT, VIRIDIS,  # noqa: E402
                           footer_config, setup_style, title_block)

INTERIM = ROOT / "data" / "interim"
RAW = ROOT / "data" / "raw"
FIGS = ROOT / "outputs" / "figures"
MIN_DEPTH = 0.10

# Worst-affected localities in E1 per the press (Gujarat Samachar 23 Jul;
# DeshGujarat 25 Jul: "the Bopal-Ghuma-Shela belt was among the worst-affected").
WORST = ("Bopal", "Ghuma", "Shela", "Jodhpur", "Vejalpur", "Makarba")
LABEL_OFFSETS = {"Bopal": (-900, 500), "Ghuma": (-1400, -900), "Shela": (-1300, -900),
                 "Makarba": (400, -900), "Sarkhej": (-1800, -700), "Jodhpur": (500, 150),
                 "Vejalpur": (500, -500), "Thaltej": (-1500, 400), "Bodakdev": (500, 300)}
SOURCES = ("Copernicus GLO-30 DEM; FABDEM v1-2 (Hawker et al. 2022, CC BY-NC-SA 4.0); "
           "© OpenStreetMap contributors (ODbL)")


def _read(stem: str):
    with rasterio.open(INTERIM / f"{stem}.tif") as s:
        a = s.read(1)
        b = s.bounds
    return a, (b.left, b.right, b.bottom, b.top)


def _places():
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    p = json.loads((RAW / "places" / "nominatim_places.json").read_text())
    return {k: tr.transform(float(v["lon"]), float(v["lat"])) for k, v in p.items() if v}


def _rivers():
    from studies.ahmedabad.terrain import CRS
    tr = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    ways = json.loads((RAW / "osm" / "waterways.json").read_text())["elements"]
    return [np.array([tr.transform(q["lon"], q["lat"]) for q in el["geometry"]])
            for el in ways if el["tags"].get("waterway") == "river"]


def _base(ax, extent, hill):
    ax.imshow(hill, extent=extent, cmap="Greys_r", vmin=0, vmax=1, alpha=0.35,
              interpolation="bilinear")
    for line in _rivers():
        ax.plot(line[:, 0], line[:, 1], color=MUTED, lw=1.1, alpha=0.9, zorder=3)
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])   # OSM ways run past the domain
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _scalebar(ax, extent, km=5):
    x0 = extent[0] + 0.05 * (extent[1] - extent[0]); y0 = extent[2] + 0.05 * (extent[3] - extent[2])
    ax.plot([x0, x0 + km * 1000], [y0, y0], color=TEXT, lw=2, solid_capstyle="butt", zorder=6)
    ax.text(x0 + km * 500, y0 + 500, f"{km} km", ha="center", va="bottom", fontsize=9,
            fontfamily=FONT_SEMIBOLD, color=TEXT, zorder=6)


def _labels(ax, places, which=None):
    for name, (x, y) in places.items():
        if which and name not in which:
            continue
        worst = name in WORST
        ax.scatter([x], [y], s=26 if worst else 14, facecolor=TEXT if worst else "white",
                   edgecolor=TEXT, lw=0.9, zorder=7)
        dx, dy = LABEL_OFFSETS.get(name, (500, 300))
        ax.text(x + dx, y + dy, name, fontsize=9.5 if worst else 8.5,
                fontfamily=FONT_BOLD if worst else "Archivo", color=TEXT, zorder=7,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.7))


def _footer(fig, lines):
    for i, line in enumerate(lines):
        footer_config(fig, line, x=0.04, y=0.03 - 0.018 * i, size=8.5)


def _hill(dem):
    ls = LightSource(azdeg=315, altdeg=45)
    return ls.hillshade(np.nan_to_num(dem, nan=np.nanmean(dem)), vert_exag=8, dx=30, dy=30)


def _dep_layer(dep):
    return np.ma.masked_less(dep, MIN_DEPTH)


def _colorbar(fig, rect, norm, label, reverse=False):
    cax = fig.add_axes(rect)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=VIRIDIS.reversed() if reverse else VIRIDIS)
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=9, colors=MUTED, length=0)
    cb.set_label(label, fontsize=9.5, fontfamily=FONT_SEMIBOLD, color=TEXT, labelpad=4)


def dem_effect() -> Path:
    fab, ext = _read("dem_fabdem")
    hill = _hill(fab)
    places = _places()
    fig, axes = plt.subplots(1, 2, figsize=(14, 7.6))
    fig.subplots_adjust(left=0.04, right=0.96, top=0.8, bottom=0.2, wspace=0.04)
    norm = Normalize(0, 3)
    for ax, name, lab in zip(axes, ("glo30", "fabdem"),
                             ("GLO-30: the surface, buildings included",
                              "FABDEM: bare earth, buildings and trees removed")):
        dep, _ = _read(f"depdepth_{name}")
        share = float((dep >= MIN_DEPTH).mean())
        _base(ax, ext, hill)
        ax.imshow(_dep_layer(dep), extent=ext, cmap=VIRIDIS, norm=norm, interpolation="nearest",
                  zorder=2)
        _labels(ax, places, which=("Bopal", "Maninagar", "Gota"))
        ax.text(0.0, 1.02, lab, transform=ax.transAxes, fontsize=12.5, fontfamily=FONT_BOLD,
                color=TEXT)
        ax.text(0.0, 0.975, f"{share:.0%} of the area in a depression ≥ 10 cm deep",
                transform=ax.transAxes, fontsize=10.5, fontfamily=FONT_SEMIBOLD, color=MUTED,
                va="top", bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.8))
    _scalebar(axes[1], ext)
    _colorbar(fig, [0.36, 0.125, 0.28, 0.022], norm,
              "Depression depth: how much water a cell holds before it spills (m, capped at 3)")
    title_block(fig, "Buildings in the elevation model invent ponds everywhere",
                "Where water would stand if nothing drained, on two 30 m models of the same "
                "ground in and around Ahmedabad", x=0.04, y_title=0.93, y_sub=0.885)
    _footer(fig, [f"Sources: {SOURCES}.",
                  "Both models are built from TanDEM-X data acquired 2011-15. Depressions from pit "
                  "and depression filling (pysheds).   Chart: Sahasrik Ragani"])
    FIGS.mkdir(parents=True, exist_ok=True)
    out = FIGS / "t1_dem_depressions.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def west() -> Path:
    fab, ext = _read("dem_fabdem")
    dep, _ = _read("depdepth_fabdem")
    hand, _ = _read("hand_fabdem")
    hill = _hill(fab)
    places = _places()
    # zoom on the city: the AMC extent plus a margin (DESIGN §4)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    (x0, y0), (x1, y1) = tr.transform(72.42, 22.94), tr.transform(72.70, 23.14)
    zoom = (x0, x1, y0, y1)

    fig, axes = plt.subplots(1, 2, figsize=(14, 7.4))
    fig.subplots_adjust(left=0.04, right=0.96, top=0.8, bottom=0.2, wspace=0.04)
    dnorm, hnorm = Normalize(0, 2), Normalize(0, 5)
    panels = ((dep, dnorm, False, "Where rain would pond",
               "Bare-earth depressions ≥ 10 cm"),
              (hand, hnorm, True, "How close the ground sits to drainage",
               "Height above nearest drainage (HAND); yellow = lowest; white = no drainage path"))
    for ax, (arr, norm, rev, head, sub) in zip(axes, panels):
        _base(ax, ext, hill)
        layer = _dep_layer(arr) if arr is dep else arr
        ax.imshow(layer, extent=ext, cmap=VIRIDIS.reversed() if rev else VIRIDIS, norm=norm,
                  interpolation="nearest", zorder=2, alpha=1.0 if arr is dep else 0.75)
        _labels(ax, places)
        ax.set_xlim(zoom[0], zoom[1]); ax.set_ylim(zoom[2], zoom[3])
        ax.text(0.0, 1.05, head, transform=ax.transAxes, fontsize=12.5, fontfamily=FONT_BOLD,
                color=TEXT)
        ax.text(0.0, 1.015, sub, transform=ax.transAxes, fontsize=10, fontfamily=FONT_SEMIBOLD,
                color=MUTED)
    _scalebar(axes[1], zoom, km=2)
    _colorbar(fig, [0.12, 0.125, 0.26, 0.022], dnorm, "Depression depth (m, capped at 2)")
    _colorbar(fig, [0.62, 0.125, 0.26, 0.022], hnorm, "HAND (m, capped at 5)", reverse=True)
    title_block(fig, "The flooded west doesn't stand out in the terrain",
                "Bold: localities worst hit on 23-25 July 2026. On bare earth they sit in no more "
                "depressions than the east, and HAND is low almost everywhere", x=0.04, y_title=0.94,
                y_sub=0.9)
    _footer(fig, [f"Sources: {SOURCES}; worst-hit localities from Gujarat Samachar (23 Jul) and "
                  "DeshGujarat (25 Jul).",
                  "30 m DEM from 2011-15 data, before much of Bopal-Shela was built. HAND drainage: "
                  "1 km² flow-accumulation channels plus OSM rivers.   Chart: Sahasrik Ragani"])
    out = FIGS / "t2_terrain_west.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


if __name__ == "__main__":
    setup_style()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in (("dem_effect", dem_effect), ("west", west)):
        if which in (name, "all"):
            print(f"  wrote {fn().relative_to(ROOT)}")
