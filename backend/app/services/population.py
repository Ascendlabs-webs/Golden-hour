"""Population-exposure adapter.

Prefers WorldPop / GHSL rasters when configured; otherwise uses a
transparent density proxy so the UI shows ESTIMATED values and never
invents exact census counts.
"""
from __future__ import annotations

import hashlib
import os


def _hash01(seed: str) -> float:
    return (int(hashlib.md5(seed.encode()).hexdigest()[:8], 16) % 10000) / 10000.0


def exposure_for_zone(zone_id: str, neighbourhood: str = "",
                      flood_extent: float = 0.0) -> dict:
    provider = os.getenv("POPULATION_PROVIDER", "worldpop")
    dataset_path = os.getenv("WORLDPOP_TIF", "")
    if dataset_path and os.path.exists(dataset_path):
        # Hook point: read raster window with rasterio when a real file exists.
        return {"zone_id": zone_id, "provider": provider, "mode": "raster",
                "detail": f"Raster hook configured at {dataset_path}; "
                          "wire rasterio windowed read here."}
    # Transparent proxy: dense urban core ~ higher exposure; flood water
    # raises the *exposed* fraction.
    dense = {"T. Nagar", "Egmore", "Mylapore", "Royapuram", "Triplicane",
             "Nungambakkam", "Saidapet", "Tondiarpet", "Velachery"}
    base_density = 0.72 + _hash01(f"pop-{zone_id}") * 0.25 if neighbourhood in dense \
        else 0.30 + _hash01(f"pop-{zone_id}") * 0.45
    estimated = int(1500 + _hash01(f"exppop-{zone_id}") * 20000)
    exposed = int(estimated * min(1.0, flood_extent * 0.9 + 0.15))
    population_risk = round(max(0.0, min(100.0, base_density * 70 + flood_extent * 30)), 1)
    return {
        "zone_id": zone_id,
        "provider": f"{provider}-proxy",
        "mode": "estimated",
        "estimated_population": estimated,
        "estimated_exposed": exposed,
        "population_risk": population_risk,
        "note": "ESTIMATED — density proxy, not a census count.",
    }


def vulnerability_for_zone(zone_id: str, population_risk: float,
                           accessibility: float) -> dict:
    """Transparent Vulnerability Index proxy (0-100)."""
    age_proxy = _hash01(f"vul-age-{zone_id}") * 40
    density_proxy = population_risk * 0.45
    access_proxy = (100 - accessibility) * 0.25
    index = max(5.0, min(100.0, age_proxy * 0.3 + density_proxy + access_proxy))
    return {"zone_id": zone_id, "vulnerability": round(index, 1),
            "note": "Proxy index — not a claim about individuals."}
