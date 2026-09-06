"""Backwards-compatible shim + shared helpers.

New code lives in :mod:`provider`, :mod:`sentinel1`, :mod:`sentinel2` and
:mod:`analysis`. This module keeps the deterministic demo helpers and the
Google Earth Engine status check in one place.
"""
from __future__ import annotations

import hashlib
import os

from .sentinel1 import fetch_preview as s1_fetch_preview  # noqa: F401
from .sentinel1 import latest_cached as s1_latest_cached  # noqa: F401
from .sentinel1 import search as sentinel1_search_live  # noqa: F401
from .sentinel2 import fetch_preview as s2_fetch_preview  # noqa: F401
from .sentinel2 import search as sentinel2_search_live  # noqa: F401


def _hash01(seed: str) -> float:
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return (h % 10000) / 10000.0


def sentinel1_demo_backscatter(zone_id: str) -> dict:
    """Deterministic prototype backscatter change (dB) per zone for demo mode."""
    pre_db = -14.0 + _hash01(f"s1pre-{zone_id}") * 6.0
    drop = 2.0 + _hash01(f"s1drop-{zone_id}") * 7.0
    post_db = pre_db - drop
    return {"pre_db": round(pre_db, 2), "post_db": round(post_db, 2),
            "delta_db": round(post_db - pre_db, 2)}


def sentinel2_ndwi_demo(zone_id: str) -> dict:
    """Deterministic prototype NDWI values per zone for demo mode."""
    green = 0.08 + _hash01(f"s2g-{zone_id}") * 0.25
    nir = 0.10 + _hash01(f"s2n-{zone_id}") * 0.30
    ndwi = (green - nir) / (green + nir) if (green + nir) else 0.0
    return {"green": round(green, 3), "nir": round(nir, 3), "ndwi": round(ndwi, 3)}


def sentinel1_search(bbox: list[float], start: str, end: str) -> dict:
    """Legacy entry point kept for older callers: open search, no credentials.

    Raises RuntimeError when unreachable (caller falls back to demo).
    """
    return sentinel1_search_live(bbox, start, end)


def gee_status() -> dict:
    """Google Earth Engine integration status (credentials never leave backend)."""
    enabled = os.getenv("EARTH_ENGINE_ENABLED", "false").lower() == "true"
    if not enabled:
        return {"enabled": False, "status": "disabled",
                "detail": "Set EARTH_ENGINE_ENABLED=true with a service-account key to enable."}
    project = os.getenv("GEE_PROJECT", "")
    key = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not project or not key:
        return {"enabled": True, "status": "misconfigured",
                "detail": "EARTH_ENGINE_ENABLED=true but GEE_PROJECT / credentials missing."}
    try:
        import ee  # type: ignore
        return {"enabled": True, "status": "ready", "detail": f"GEE project {project}."}
    except ImportError:
        return {"enabled": True, "status": "unavailable",
                "detail": "earthengine-api package not installed (pip install earthengine-api)."}
