"""Prototype flood analysis on real satellite observations.

Pipeline (all steps use REAL retrieved metadata/imagery in LIVE mode):

    STAC search (S1 RTC + S2 L2A, cloud-filtered)
        -> cache metadata (data/raw/sentinel1|s2/)
        -> download open preview renders
        -> map study-area grid cells to pixel windows (linear lon/lat
           mapping across the scene bbox — previews render full extent)
        -> per-zone dark-pixel fraction (calm water backscatters little,
           so standing water renders dark in SAR previews)
        -> pre/post change comparison
        -> flood_extent / change_score / satellite_confidence per zone

Label: **Prototype SAR Flood Detection**. This is a transparent,
preview-based prototype — not a production flood model and not a
replacement for calibrated backscatter processing (which needs
rasterio/GDAL; see README).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from .. import config as cfg

# Pixel is "dark" (water-like) below this 0-255 brightness in SAR previews.
SAR_DARK_THRESHOLD = 60
# Normalisation: dark fractions map [LO, LO+RANGE] -> extent [0, 1].
SAR_DARK_LO = 0.05
SAR_DARK_RANGE = 0.50
OPTICAL_DARK_THRESHOLD = 70
# Fusion weights when both sensors contribute.
W_S1 = 0.70
W_S2 = 0.30


def compute_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Real NDWI = (Green - NIR) / (Green + NIR) on reflectance arrays.

    Operates on real band arrays when available (e.g. rasterio windowed
    reads of B03/B08). Live preview path cannot supply calibrated NIR, so
    it uses the visual proxy below instead — never mislabelled as NDWI.
    """
    green = np.asarray(green, dtype=float)
    nir = np.asarray(nir, dtype=float)
    denom = green + nir
    with np.errstate(divide="ignore", invalid="ignore"):
        ndwi = np.where(denom == 0, 0.0, (green - nir) / denom)
    return np.clip(ndwi, -1.0, 1.0)


def optical_water_proxy(rgb: np.ndarray) -> np.ndarray:
    """Visible-water proxy (0..1) from TRUE-COLOUR preview pixels.

    NOT NDWI (no NIR band in previews). Open water tends to be dark with
    blue >= red; used only as corroborating evidence beside SAR.
    """
    rgb = np.asarray(rgb, dtype=float)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    score = ((b - r) / 255.0 * 0.6 + (g - r) / 255.0 * 0.2
             + np.clip((120.0 - bright) / 120.0, 0, 1) * 0.5)
    return np.clip(score, 0, 1)


def _scene_bbox(feature_bbox: list[float] | None, fallback: list[float]) -> list[float]:
    if feature_bbox and len(feature_bbox) == 4:
        return [float(x) for x in feature_bbox]
    return [float(x) for x in fallback]


def zone_pixel_window(img_w: int, img_h: int, scene_bbox: list[float],
                      study_bbox: list[float], row: int, col: int,
                      rows: int, cols: int) -> tuple[int, int, int, int]:
    """Pixel window (left, upper, right, lower) for one grid cell."""
    s_min_lon, s_min_lat, s_max_lon, s_max_lat = scene_bbox
    st_min_lon, st_min_lat, st_max_lon, st_max_lat = study_bbox
    cell_lon = (st_max_lon - st_min_lon) / cols
    cell_lat = (st_max_lat - st_min_lat) / rows
    # row 0 = north
    c_top = st_max_lat - row * cell_lat
    c_bottom = c_top - cell_lat
    c_left = st_min_lon + col * cell_lon
    c_right = c_left + cell_lon

    def x(lon: float) -> int:
        return int((lon - s_min_lon) / (s_max_lon - s_min_lon) * img_w)

    def y(lat: float) -> int:
        return int((s_max_lat - lat) / (s_max_lat - s_min_lat) * img_h)

    left, right = sorted((x(c_left), x(c_right)))
    upper, lower = sorted((y(c_top), y(c_bottom)))
    left = max(0, min(img_w - 1, left))
    right = max(left + 1, min(img_w, right))
    upper = max(0, min(img_h - 1, upper))
    lower = max(upper + 1, min(img_h, lower))
    return left, upper, right, lower


def _dark_fraction(crop: Image.Image, threshold: int) -> float:
    gray = crop.convert("L")
    arr = np.asarray(gray, dtype=float)
    if arr.size == 0:
        return 0.0
    return float((arr < threshold).mean())


def _normalise_dark(frac: float) -> float:
    return round(max(0.0, min(1.0, (frac - SAR_DARK_LO) / SAR_DARK_RANGE)), 3)


def analyse_scene(preview_path: Path, scene_bbox: list[float],
                  study_bbox: list[float], rows: int, cols: int,
                  threshold: int = SAR_DARK_THRESHOLD,
                  optical: bool = False) -> dict:
    """Per-zone dark/water fractions for one cached preview scene."""
    img = Image.open(preview_path).convert("RGB")
    w, h = img.size
    zones: dict[str, dict] = {}
    for r in range(rows):
        for c in range(cols):
            zid = f"Z-{r * cols + c + 1:03d}"
            box = zone_pixel_window(w, h, scene_bbox, study_bbox, r, c, rows, cols)
            crop = img.crop(box)
            if optical:
                proxy = optical_water_proxy(np.asarray(crop))
                frac = float((proxy > 0.5).mean())
            else:
                frac = _dark_fraction(crop, threshold)
            zones[zid] = {"dark_fraction": round(frac, 4),
                          "extent": _normalise_dark(frac)}
    return {"zones": zones, "image_size": [w, h], "scene_bbox": scene_bbox}


def fuse(post: dict, pre: dict | None, s2: dict | None) -> dict:
    """Fuse S1 post (+pre change) with optional S2 corroboration per zone."""
    out: dict[str, dict] = {}
    for zid, zpost in post["zones"].items():
        s1_ext = zpost["extent"]
        if pre and zid in pre["zones"]:
            delta = abs(zpost["dark_fraction"] - pre["zones"][zid]["dark_fraction"])
            change = round(max(0.0, min(100.0, delta * 220.0)), 1)
        else:
            change = round(s1_ext * 60.0, 1)  # single-scene fallback, documented
        if s2 and zid in s2["zones"]:
            s2_ext = s2["zones"][zid]["extent"]
            extent = round(W_S1 * s1_ext + W_S2 * s2_ext, 3)
            evidence = ["sentinel-1", "sentinel-2"]
        else:
            extent = s1_ext
            evidence = ["sentinel-1"]
        confidence = round(max(35.0, min(95.0, 55.0 + extent * 30.0 + change * 0.15)), 1)
        out[zid] = {
            "flood_extent_percent": round(extent * 100, 1),
            "flood_extent": extent,
            "flood_severity": int(round(extent * 100)),
            "change_score": change,
            "satellite_confidence": confidence,
            "evidence": evidence,
        }
    return out


def write_analysis(analysis_id: str, payload: dict) -> Path:
    p = cfg.FLOOD_DIR / f"{analysis_id}.json"
    p.write_text(json.dumps({"analysis_id": analysis_id,
                             "created_at": datetime.now(timezone.utc).isoformat(),
                             **payload}, indent=2))
    return p
