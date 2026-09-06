"""Sentinel-1 SAR adapter: search, cache, preview retrieval.

Primary: Planetary Computer ``sentinel-1-rtc`` STAC (open, no key).
Fallback: Copernicus OData catalogue (open search).
Full-resolution download from Copernicus needs an account and is NOT
required — the pipeline works on open preview renders + metadata.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from . import provider as prov


def _cache_paths(product_id: str) -> tuple[Path, Path]:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in product_id)
    return (cfg.S1_RAW_DIR / f"{safe}.json", cfg.S1_RAW_DIR / f"{safe}.preview.png")


def search(bbox: list[float] | None = None, start: str = "2026-08-01",
           end: str = "2026-09-06", limit: int = 5) -> dict:
    """Return real product metadata; raises RuntimeError if unreachable."""
    bbox = bbox or cfg.STUDY_AREA["bbox"]
    errors: list[str] = []
    try:
        feats = prov.stac_search(cfg.S1_COLLECTION, bbox, start, end, limit,
                                 sortby=[{"field": "properties.datetime",
                                          "direction": "desc"}])
        products = [prov.parse_stac_item(f) for f in feats]
        return {"provider": "planetary-computer", "satellite": "Sentinel-1",
                "count": len(products), "products": products,
                "queried_at": datetime.now(timezone.utc).isoformat()}
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        products = prov.copernicus_search("SENTINEL-1", bbox, start, end, limit)
        return {"provider": "copernicus-dataspace", "satellite": "Sentinel-1",
                "count": len(products), "products": products,
                "queried_at": datetime.now(timezone.utc).isoformat(),
                "note": "STAC unreachable; Copernicus fallback used."}
    except RuntimeError as exc:
        errors.append(str(exc))
    raise RuntimeError("Sentinel-1 unavailable: " + " | ".join(errors))


def cache_product(product: dict) -> Path:
    """Persist product metadata; returns metadata path."""
    meta_path, _ = _cache_paths(product["product_id"])
    meta_path.write_text(json.dumps(product, indent=2))
    return meta_path


def fetch_preview(product: dict, timeout: int = 60) -> Path:
    """Download (or reuse cached) open preview render for a product."""
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


def latest_cached() -> dict | None:
    """Most recently acquired cached S1 product metadata, if any."""
    best, best_dt = None, ""
    for p in cfg.S1_RAW_DIR.glob("*.json"):
        try:
            m = json.loads(p.read_text())
        except Exception:
            continue
        if (m.get("acquisition_time") or "") > best_dt:
            best, best_dt = m, m.get("acquisition_time") or ""
    return best
