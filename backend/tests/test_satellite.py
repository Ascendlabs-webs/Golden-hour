"""Satellite + flood-analysis tests (pure functions + failure handling).

Network-touching search functions are tested with monkeypatched providers
so the suite runs offline; one live test is opt-in via GH_LIVE_TEST=1.
"""
import json
import os

import numpy as np
import pytest
from PIL import Image

from backend.app.satellite import analysis as an
from backend.app.satellite import provider as prov

BBOX = [80.05, 12.90, 80.32, 13.25]


def _fake_feature(pid="P1", dt="2026-08-29T00:31:38Z", cloud=None):
    return {
        "id": pid, "collection": "sentinel-1-rtc",
        "bbox": [78.0, 11.0, 81.0, 13.5],
        "geometry": None,
        "properties": {"datetime": dt, "eo:cloud_cover": cloud},
        "assets": {"rendered_preview": {"href": "http://example.com/p.png",
                                        "roles": ["visual"]}},
    }


def test_parse_stac_item():
    m = prov.parse_stac_item(_fake_feature())
    assert m["product_id"] == "P1"
    assert m["satellite"] == "Sentinel-1"
    assert m["acquisition_time"] == "2026-08-29T00:31:38Z"
    assert m["preview_href"] == "http://example.com/p.png"


def test_parse_stac_item_s2():
    f = _fake_feature(pid="S2A", dt="2026-09-01T04:57:01Z", cloud=0.79)
    f["collection"] = "sentinel-2-l2a"
    m = prov.parse_stac_item(f)
    assert m["satellite"] == "Sentinel-2"
    assert m["cloud_cover"] == 0.79


def test_search_failure_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(prov, "stac_search", boom)
    monkeypatch.setattr(prov, "copernicus_search", boom)
    from backend.app.satellite import sentinel1 as s1
    with pytest.raises(RuntimeError, match="unavailable"):
        s1.search(BBOX)


def test_ndwi_known_values():
    green = np.array([[0.2, 0.4]])
    nir = np.array([[0.1, 0.5]])
    out = an.compute_ndwi(green, nir)
    assert out.shape == (1, 2)
    assert abs(out[0, 0] - (0.1 / 0.3)) < 1e-9
    assert abs(out[0, 1] - (-0.1 / 0.9)) < 1e-9


def test_ndwi_zero_denom_safe():
    out = an.compute_ndwi(np.zeros((2, 2)), np.zeros((2, 2)))
    assert (out == 0).all()


def test_optical_proxy_bounds():
    rgb = (np.random.default_rng(7).random((10, 10, 3)) * 255).astype(np.uint8)
    p = an.optical_water_proxy(rgb)
    assert p.min() >= 0 and p.max() <= 1


def test_zone_pixel_window_geometry():
    w, h = 1024, 786
    scene = [78.0, 11.0, 81.0, 13.5]
    left, upper, right, lower = an.zone_pixel_window(w, h, scene, BBOX, 0, 0, 6, 6)
    assert 0 <= left < right <= w and 0 <= upper < lower <= h
    # north-west cell maps to upper-left area
    l2, _, _, _ = an.zone_pixel_window(w, h, scene, BBOX, 0, 5, 6, 6)
    assert l2 > left


def _synthetic_preview(path, dark_cells=frozenset()):
    """1024x768 RGB; dark_cells = {(row,col)} painted near-black."""
    img = Image.new("RGB", (1024, 768), (150, 150, 150))
    px = img.load()
    cw, ch = 1024 // 6, 768 // 6
    for (r, c) in dark_cells:
        for y in range(r * ch, (r + 1) * ch):
            for x in range(c * cw, (c + 1) * cw):
                px[x, y] = (20, 20, 20)
    img.save(path)


def test_analyse_scene_detects_dark_cell(tmp_path):
    p = tmp_path / "scene.png"
    _synthetic_preview(p, {(2, 3)})
    res = an.analyse_scene(p, [80.0, 12.0, 81.0, 14.0],
                           [80.0, 12.0, 81.0, 14.0], 6, 6)
    assert len(res["zones"]) == 36
    assert res["zones"]["Z-016"]["extent"] > 0.8  # row2 col3
    assert res["zones"]["Z-001"]["extent"] < 0.2


def test_fuse_prefers_change_and_evidence(tmp_path):
    post = {"zones": {"Z-001": {"dark_fraction": 0.6, "extent": 0.9}}}
    pre = {"zones": {"Z-001": {"dark_fraction": 0.1, "extent": 0.1}}}
    fused = an.fuse(post, pre, None)
    m = fused["Z-001"]
    assert m["flood_extent_percent"] == 90.0
    assert m["change_score"] > 50
    assert m["evidence"] == ["sentinel-1"]
    s2 = {"zones": {"Z-001": {"dark_fraction": 0.2, "extent": 0.2}}}
    fused2 = an.fuse(post, pre, s2)
    assert fused2["Z-001"]["evidence"] == ["sentinel-1", "sentinel-2"]
    assert fused2["Z-001"]["flood_extent"] < 0.9  # fusion blends


def test_pick_pre_post():
    from backend.app.processing import pipeline as pipe
    prods = [
        {"product_id": "new", "acquisition_time": "2026-08-29T00:00:00Z"},
        {"product_id": "mid", "acquisition_time": "2026-08-10T00:00:00Z"},
        {"product_id": "old", "acquisition_time": "2026-06-01T00:00:00Z"},
    ]
    post, pre = pipe._pick_pre_post(prods)
    assert post["product_id"] == "new"
    assert pre["product_id"] == "old"  # >20 days older


@pytest.mark.skipif(os.getenv("GH_LIVE_TEST") != "1", reason="opt-in live network test")
def test_live_stac_search_chennai():
    from backend.app.satellite import sentinel1 as s1
    res = s1.search(BBOX)
    assert res["count"] >= 1
    assert res["products"][0]["acquisition_time"]
