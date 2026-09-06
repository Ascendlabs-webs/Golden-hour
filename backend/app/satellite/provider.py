"""Satellite provider abstraction.

Two officially documented, scrape-free providers (no credentials needed
for *search*; downloads of open STAC preview assets also need no key):

* ``planetary``  — Microsoft Planetary Computer STAC API (primary).
* ``copernicus`` — Copernicus Data Space OData catalogue (fallback/metadata).

Full-resolution product *downloads* from Copernicus need an account; the
pipeline only ever fetches small open preview renders + metadata, so LIVE
mode works without any credentials.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .. import config as cfg

HEADERS = {"Accept": "application/json", "User-Agent": "GoldenHourAI/1.0 (academic prototype)"}


def _http_json(url: str, timeout: int = 25, method: str = "GET",
               payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={**HEADERS, "Content-Type": "application/json"},
                                 method=method if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _http_bytes(url: str, timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")


def stac_search(collection: str, bbox: list[float], start: str, end: str,
                limit: int = 5, query: dict | None = None,
                sortby: list[dict] | None = None) -> list[dict]:
    """Search Planetary Computer STAC. Raises RuntimeError on failure."""
    body: dict = {
        "collections": [collection],
        "bbox": bbox,
        "datetime": f"{start}/{end}",
        "limit": limit,
    }
    if query:
        body["query"] = query
    if sortby:
        body["sortby"] = sortby
    try:
        res = _http_json(f"{cfg.STAC_API_URL}/search", method="POST", payload=body)
    except Exception as exc:
        raise RuntimeError(f"STAC search failed ({collection}): {exc}") from exc
    return res.get("features", [])


def parse_stac_item(feature: dict, provider: str = "planetary-computer") -> dict:
    """Normalise a STAC feature into our product metadata record."""
    props = feature.get("properties", {})
    assets = feature.get("assets", {})
    preview = (assets.get("rendered_preview") or {}).get("href")
    return {
        "product_id": feature.get("id"),
        "provider": provider,
        "satellite": "Sentinel-1" if "sentinel-1" in str(
            feature.get("collection", "")) else "Sentinel-2",
        "collection": feature.get("collection"),
        "acquisition_time": props.get("datetime"),
        "cloud_cover": props.get("eo:cloud_cover"),
        "bbox": feature.get("bbox"),
        "geometry": feature.get("geometry"),
        "preview_href": preview,
        "assets": {k: {"href": v.get("href"), "roles": v.get("roles", [])}
                   for k, v in assets.items()},
        "searched_at": datetime.now(timezone.utc).isoformat(),
    }


def copernicus_search(sensor: str, bbox: list[float], start: str, end: str,
                      top: int = 5) -> list[dict]:
    """Open Copernicus OData catalogue search (no credentials required)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    filt = (
        f"Collection/Name eq '{sensor}' and OData.CSC.Intersects(area=geography'SRID=4326;"
        f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},{max_lon} {max_lat},"
        f"{min_lon} {max_lat},{min_lon} {min_lat}))') "
        f"and ContentDate/Start gt {start}T00:00:00.000Z "
        f"and ContentDate/Start lt {end}T23:59:59.999Z"
    )
    url = (f"{cfg.COPERNICUS_ODATA_URL}/Products?$filter="
           f"{urllib.parse.quote(filt)}&$top={top}")
    try:
        payload = _http_json(url)
    except Exception as exc:
        raise RuntimeError(f"Copernicus catalogue query failed: {exc}") from exc
    out = []
    for p in payload.get("value", []):
        out.append({
            "product_id": p.get("Id"),
            "provider": "copernicus-dataspace",
            "satellite": "Sentinel-1" if "SENTINEL-1" in sensor else "Sentinel-2",
            "collection": sensor,
            "name": p.get("Name"),
            "acquisition_time": (p.get("ContentDate") or {}).get("Start"),
            "cloud_cover": None,
            "preview_href": None,
            "searched_at": datetime.now(timezone.utc).isoformat(),
        })
    return out
