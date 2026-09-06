"""OpenStreetMap road-accessibility adapter.

Live path queries the Overpass API for road geometry inside the bbox.
Failures (network, rate-limit) fall back to deterministic demo data so the
dashboard shows 'Data temporarily unavailable' / demo state instead of
crashing.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _hash01(seed: str) -> float:
    return (int(hashlib.md5(seed.encode()).hexdigest()[:8], 16) % 10000) / 10000.0


def fetch_road_stats(bbox: list[float], timeout: int = 25) -> dict:
    """Return {road_km, blocked_roads, per_zone_road_density} from OSM.

    Raises RuntimeError on failure; caller decides fallback.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    query = (
        "[out:json][timeout:25];"
        f"(way['highway'~'^(motorway|trunk|primary|secondary|tertiary|residential|unclassified)$']"
        f"({min_lat},{min_lon},{max_lat},{max_lon}););"
        "out tags bb;"
    )
    req = urllib.request.Request(OVERPASS_URL, data=query.encode(),
                                 headers={"Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:
        raise RuntimeError(f"OSM Overpass query failed: {exc}") from exc
    ways = payload.get("elements", [])
    # Rough length proxy from bounding-box diagonal of each way.
    total = 0.0
    for w in ways:
        b = w.get("bounds", {})
        if b:
            total += abs(b.get("maxlat", 0) - b.get("minlat", 0)) * 111.0
            total += abs(b.get("maxlon", 0) - b.get("minlon", 0)) * 109.0
    return {
        "provider": "openstreetmap-overpass",
        "way_count": len(ways),
        "road_km_estimate": round(total, 1),
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }


def accessibility_for_zone(zone_id: str, flood_extent: float,
                           blocked_nearby: int = 0) -> dict:
    """Deterministic demo accessibility: 100 = fully accessible.

    Flood water + blocked roads reduce the score transparently.
    """
    base = 55 + _hash01(f"osm-{zone_id}") * 40  # 55..95 road-density proxy
    penalty = flood_extent * 45 + min(blocked_nearby, 5) * 4
    score = max(5.0, min(100.0, base - penalty))
    return {
        "zone_id": zone_id,
        "road_density_proxy": round(base, 1),
        "blocked_nearby": blocked_nearby,
        "accessibility": round(score, 1),
    }
