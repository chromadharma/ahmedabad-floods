import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fetch", Path(__file__).resolve().parents[1] / "scripts" / "fetch.py")
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class Affine:
    """Stand-in for a GCPTransformer: 10 m-ish pixels, north-up."""
    def rowcol(self, xs, ys):
        return ([int((24.0 - y) * 10000) for y in ys], [int((x - 72.0) * 10000) for x in xs])


def test_pixel_window_is_padded_snapped_and_clipped():
    win = fetch.pixel_window(Affine(), (72.35, 22.85, 72.80, 23.20), (16724, 25749))
    r0, r1, c0, c1 = win
    assert r0 % 1024 == 0 and c0 % 1024 == 0
    assert r0 <= 8000 - 512 and r1 >= 11500 + 512          # bbox rows 8000-11500
    assert c0 <= 3500 - 512 and c1 >= 8000 + 512           # bbox cols 3500-8000
    assert r1 <= 16724 and c1 <= 25749


def test_pixel_window_misses_image():
    assert fetch.pixel_window(Affine(), (60.0, 30.0, 60.1, 30.1), (100, 100)) is None


def test_select_scenes_by_footprint():
    def fp(w, s, e, n):
        return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    inside = {"id": "a", "footprint": fp(70.0, 22.6, 72.5, 24.5)}    # overlaps the west strip
    north = {"id": "b", "footprint": fp(70.0, 24.5, 73.0, 26.0)}     # clear of the city
    assert [i["id"] for i in fetch.select_scenes([inside, north])] == ["a"]
