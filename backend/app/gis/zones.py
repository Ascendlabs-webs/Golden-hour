"""Geographic grid + GeoJSON generation over the study-area bbox."""
from __future__ import annotations


def grid_cell_polygon(bbox: list[float], row: int, col: int, rows: int, cols: int) -> list[list[list[float]]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    dlon = (max_lon - min_lon) / cols
    dlat = (max_lat - min_lat) / rows
    # row 0 = north (max_lat side)
    top = max_lat - row * dlat
    bottom = top - dlat
    left = min_lon + col * dlon
    right = left + dlon
    ring = [[left, top], [right, top], [right, bottom], [left, bottom], [left, top]]
    return [ring]


def zone_feature(zone: dict, bbox: list[float], rows: int, cols: int,
                 score_total: int, priority: str) -> dict:
    coords = grid_cell_polygon(bbox, zone["row"], zone["col"], rows, cols)
    return {
        "type": "Feature",
        "properties": {
            "zone_id": zone["zone_id"],
            "neighbourhood": zone.get("neighbourhood"),
            "severity": zone.get("severity"),
            "population_risk": zone.get("population_risk"),
            "vulnerability": zone.get("vulnerability"),
            "accessibility": zone.get("accessibility"),
            "confidence": zone.get("confidence"),
            "reports_count": zone.get("reports_count"),
            "incident_type": zone.get("incident_type"),
            "flood_extent": zone.get("flood_extent"),
            "estimated_population": zone.get("estimated_population"),
            "golden_hour_score": score_total,
            "priority_class": priority,
            "manual_override": bool(zone.get("manual_override", False)),
            "last_updated": zone.get("last_updated"),
        },
        "geometry": {"type": "Polygon", "coordinates": coords},
    }


def feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}
