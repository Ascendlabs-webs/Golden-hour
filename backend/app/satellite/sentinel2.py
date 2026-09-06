"""Sentinel-2 optical adapter: cloud-filtered search, cache, preview.

Used as *supporting evidence* (cloud cover, recency, true-colour visual
check). SAR (Sentinel-1) remains the primary flood sensor because radar
sees through clouds. If Sentinel-2 is cloudy/unavailable the pipeline
continues with Sentinel-1 alone and never crashes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from . import provider as prov


def _cache_paths(product_id: str) -> tuple[Path, Path]:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in product_id)
    return (cfg.S2_RAW_DIR / f"{safe}.json", cfg.S2_RAW_DIR / f"{safe}.preview.png")


def search(bbox: list[float] | None = None, start: str = "2026-07-01",
           end: str = "2026-09-06", cloud_max: float = 40,
           limit: int = 5) -> dict:
    """Cloud-filtered S2 L2A search. Raises RuntimeError if unreachable."""
    bbox = bbox or cfg.STUDY_AREA["bbox"]
    errors: list[str] = []
    try:
        feats = prov.stac_search(
            cfg.S2_COLLECTION, bbox, start, end, limit,
            query={"eo:cloud_cover": {"lt": cloud_max}},
            sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}])
        products = [prov.parse_stac_item(f) for f in feats]
        return {"provider": "planetary-computer", "satellite": "Sentinel-2",
                "count": len(products), "products": products,
                "cloud_max": cloud_max,
                "queried_at": datetime.now(timezone.utc).isoformat()}
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        products = prov.copernicus_search("SENTINEL-2", bbox, start, end, limit)
        return {"provider": "copernicus-dataspace", "satellite": "Sentinel-2",
                "count": len(products), "products": products,
                "cloud_max": cloud_max,
                "queried_at": datetime.now(timezone.utc).isoformat(),
                "note": "STAC unreachable; Copernicus fallback used (no cloud filter)."}
    except RuntimeError as exc:
        errors.append(str(exc))
    raise RuntimeError("Sentinel-2 unavailable: " + " | ".join(errors))


def cache_product(product: dict) -> Path:
    meta_path, _ = _cache_paths(product["product_id"])
    meta_path.write_text(json.dumps(product, indent=2))
    return meta_path


def fetch_preview(product: dict, timeout: int = 60) -> Path:
    meta_path, img_path = _cache_paths(product["product_id"])
    if img_path.exists() and img_path.stat().st_size > 10_000:
        return img_path
    href = product.get("preview_href")
    if not href:
        raise RuntimeError(f"No open preview for {product['product_id']}.")
    try:
        blob, ctype = prov._http_bytes(href, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"Preview download failed: {exc}") from exc
    if len(blob) < 10_000 or "image" not in (ctype or ""):
        raise RuntimeError(f"Preview for {product['product_id']} is not a usable image.")
    img_path.write_bytes(blob)
    product = {**product, "preview_cached_at": datetime.now(timezone.utc).isoformat(),
               "preview_bytes": len(blob)}
    meta_path.write_text(json.dumps(product, indent=2))
    return img_path
