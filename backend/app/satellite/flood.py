"""Prototype flood-detection pipeline.

Sentinel-1 SAR concept:
    pre-event backscatter -> post-event backscatter -> delta_dB
    -> water/flood classification -> flood extent per zone.

This is a transparent prototype (threshold on backscatter drop + NDWI
supporting evidence), NOT a validated flood model.
"""
from __future__ import annotations

from ..config import DAMAGE_WEIGHTS
from .sentinel import sentinel1_demo_backscatter, sentinel2_ndwi_demo


def classify_water(delta_db: float, ndwi: float) -> tuple[float, float]:
    """Return (flood_extent 0..1, change_score 0..100)."""
    # Strong backscatter drop (< -3 dB) indicates likely standing water.
    if delta_db <= -6:
        extent = 0.85
    elif delta_db <= -4:
        extent = 0.65
    elif delta_db <= -3:
        extent = 0.45
    elif delta_db <= -2:
        extent = 0.25
    else:
        extent = 0.08
    # NDWI > 0 supports open-water presence -> nudge extent up slightly.
    if ndwi > 0.1:
        extent = min(1.0, extent + 0.1)
    change_score = max(0.0, min(100.0, (-delta_db) * 12.0))
    return round(extent, 3), round(change_score, 1)


def damage_score(flood_extent: float, change_score: float,
                 building_exposure: float, imagery_confidence: float,
                 weights: dict | None = None) -> float:
    """Normalised 0-100 damage score (transparent weighted sum)."""
    w = weights or DAMAGE_WEIGHTS
    total = (flood_extent * 100 * w["flood_extent"]
             + change_score * w["change_detection"]
             + building_exposure * w["building_exposure"]
             + imagery_confidence * w["imagery_confidence"])
    return round(max(0.0, min(100.0, total)), 1)


def analyze_zone(zone_id: str, building_exposure: float = 50.0,
                 imagery_confidence: float = 70.0) -> dict:
    """Full prototype analysis for one zone (demo-mode deterministic)."""
    s1 = sentinel1_demo_backscatter(zone_id)
    s2 = sentinel2_ndwi_demo(zone_id)
    extent, change = classify_water(s1["delta_db"], s2["ndwi"])
    dmg = damage_score(extent, change, building_exposure, imagery_confidence)
    return {
        "zone_id": zone_id,
        "method": "prototype-flood-detection",
        "sentinel1": s1,
        "sentinel2": s2,
        "flood_extent": extent,
        "change_detection_score": change,
        "building_exposure": building_exposure,
        "imagery_confidence": imagery_confidence,
        "damage_score": dmg,
    }
