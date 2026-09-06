"""Ingest + processing pipeline: satellite -> flood -> exposure -> scoring.

DEMO mode rebuilds the deterministic Chennai scenario (no network).
LIVE mode runs real STAC search -> preview download -> per-zone prototype
flood analysis -> zone update -> GHS recalculation, with staged progress,
caching, audit events and graceful per-source failure handling.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from .. import database as db
from ..demo import chennai as demo
from ..scoring import ghs as scoring
from ..satellite import analysis as anamod
from ..satellite import flood as floodmod
from ..satellite import sentinel1 as s1mod
from ..satellite import sentinel2 as s2mod
from ..services import osm as osmmod
from ..services import population as popmod

# ---- lightweight event bus (WebSocket layer subscribes; no circular imports) ----
_listeners: list = []


def subscribe(fn) -> None:
    _listeners.append(fn)


def emit(event, payload=None) -> None:
    for fn in list(_listeners):
        try:
            fn(event, payload or {})
        except Exception:
            pass


def bump_data_version(note="") -> str:
    v = datetime.now(timezone.utc).isoformat()
    db.set_state("data_version", v)
    db.set_state("zones_updated_at", v)
    if note:
        db.set_state("last_update_note", note)
    return v



def _cache_path(name: str) -> Path:
    cfg.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return cfg.PROCESSED_DIR / name


def write_cache(name: str, payload: dict) -> Path:
    p = _cache_path(name)
    p.write_text(json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(),
                             "data": payload}, indent=2))
    return p


def read_cache(name: str, max_age_min: int = 120) -> dict | None:
    p = _cache_path(name)
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text())
        ts = datetime.fromisoformat(obj["cached_at"])
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        if age > max_age_min:
            return None
        return obj
    except Exception:
        return None


def default_sources(mode: str) -> list[dict]:
    demo_flag = "demo" if mode == "demo" else "connected"
    now = db.now_iso()
    return [
        {"source_id": "sentinel1", "category": "Satellite", "display_name": "Sentinel-1 SAR",
         "status": demo_flag, "last_updated": now, "last_checked": now,
         "last_successful_update": now if mode == "demo" else None,
         "acquisition_time": None, "processing_time": None,
         "detail": "Prototype SAR Flood Detection" if mode == "demo" else "Planetary Computer STAC"},
        {"source_id": "sentinel2", "category": "Satellite", "display_name": "Sentinel-2 Optical",
         "status": demo_flag, "last_updated": now, "last_checked": now,
         "last_successful_update": now if mode == "demo" else None,
         "acquisition_time": None, "processing_time": None,
         "detail": "Optical supporting evidence (cloud-filtered)"},
        {"source_id": "osm", "category": "Mapping", "display_name": "OpenStreetMap Roads",
         "status": demo_flag, "last_updated": now, "last_checked": now,
         "last_successful_update": now if mode == "demo" else None,
         "acquisition_time": None, "processing_time": None,
         "detail": "Road accessibility proxy" if mode == "demo" else "Overpass API"},
        {"source_id": "population", "category": "Population",
         "display_name": f"Population ({cfg.POPULATION_PROVIDER})",
         "status": demo_flag, "last_updated": now, "last_checked": now,
         "last_successful_update": now if mode == "demo" else None,
         "acquisition_time": None, "processing_time": None,
         "detail": "ESTIMATED exposure proxy"},
        {"source_id": "reports", "category": "Crowdsourced",
         "display_name": "Crowdsourced Reports",
         "status": "connected", "last_updated": now, "last_checked": now,
         "last_successful_update": now, "acquisition_time": None,
         "processing_time": None, "detail": "Algorithmic confidence + human verification"},
        {"source_id": "engine", "category": "Processing",
         "display_name": "GoldenHour AI Analysis Engine",
         "status": "connected", "last_updated": now, "last_checked": now,
         "last_successful_update": now, "acquisition_time": None,
         "processing_time": None, "detail": "GHS scoring engine v1"},
    ]


def score_zone_record(z: dict, t_min: float = 0) -> dict:
    urgency = scoring.compute_urgency(z.get("incident_type", "Property Damage"), t_min)
    total, breakdown, values = scoring.compute_ghs(
        z.get("severity", 50), z.get("population_risk", 50),
        z.get("vulnerability", 50), urgency,
        z.get("confidence", 50), z.get("accessibility", 50))
    priority = "Critical" if z.get("manual_override") else scoring.classify(total)
    silent = scoring.is_silent_zone(z.get("population_risk", 0), z.get("reports_count", 0))
    return {"zone_id": z["zone_id"], "golden_hour_score": total,
            "breakdown": breakdown, "values": values, "urgency": round(urgency, 1),
            "priority_class": priority,
            "silent_zone": bool(silent),
            "manual_override": bool(z.get("manual_override", False))}


def refresh_demo() -> dict:
    """Rebuild the deterministic Chennai demo scenario into SQLite + cache."""
    zones = demo.generate_demo_zones(cfg.GRID_ROWS, cfg.GRID_COLS)
    # Enrich deterministically with flood/population/OSM proxies (cached).
    for z in zones:
        fa = floodmod.analyze_zone(z["zone_id"])
        z["flood_extent"] = fa["flood_extent"]
        z["severity"] = int(fa["damage_score"])
        acc = osmmod.accessibility_for_zone(z["zone_id"], fa["flood_extent"])
        z["accessibility"] = int(acc["accessibility"])
        pop = popmod.exposure_for_zone(z["zone_id"], z["neighbourhood"], fa["flood_extent"])
        z["estimated_population"] = pop["estimated_population"]
        z["population_risk"] = int(pop["population_risk"])
        vul = popmod.vulnerability_for_zone(z["zone_id"], pop["population_risk"], acc["accessibility"])
        z["vulnerability"] = int(vul["vulnerability"])
        z["last_updated"] = db.now_iso()
    reports = demo.generate_demo_reports(zones)
    teams = demo.generate_demo_teams()
    sources = default_sources("demo")
    db.seed_all(zones, reports, teams, sources,
                "Simulation initialized — Chennai Flood Simulation loaded (DEMO DATA).")
    write_cache("demo_snapshot.json", {"zones": len(zones), "reports": len(reports)})
    version = bump_data_version("demo rebuild")
    emit("zones_updated", {"data_version": version})
    return {"zones": len(zones), "reports": len(reports), "teams": len(teams)}


def refresh_live() -> dict:
    """Live refresh: real satellite analysis + OSM, staged with audit trail.

    Never crashes the dashboard — per-source errors are recorded and
    surfaced as 'unavailable'. No random values are used in live mode.
    """
    analysis = run_live_analysis()
    notes: list[str] = list(analysis.get("errors", []))
    osm_status, osm_detail = "demo", "Road accessibility proxy (Overpass unreachable)"
    try:
        stats = osmmod.fetch_road_stats(cfg.STUDY_AREA["bbox"])
        osm_status = "connected"
        osm_detail = f"Overpass: {stats['way_count']} ways, ~{stats['road_km_estimate']} km"
        db.add_audit("OSM roads updated from Overpass API.")
    except Exception as exc:
        notes.append(str(exc))
    with db.get_conn() as conn:
        for s in db.get_sources():
            if s["source_id"] == "osm":
                s.update(status=osm_status, detail=osm_detail,
                         last_updated=db.now_iso(), last_checked=db.now_iso())
                if osm_status == "connected":
                    s["last_successful_update"] = s["last_updated"]
                db.upsert_source(conn, s)
    return {"zones": len(db.get_zones()), "reports": len(db.get_reports()),
            "teams": len(db.get_teams()), "analysis": analysis, "notes": notes}


# ================= LIVE satellite analysis =================

def _pick_pre_post(products: list[dict]) -> tuple[dict | None, dict | None]:
    """Newest product = post; newest product >20 days older = pre."""
    dated = sorted([p for p in products if p.get("acquisition_time")],
                   key=lambda p: p["acquisition_time"], reverse=True)
    if not dated:
        return None, None
    post = dated[0]
    pre = None
    try:
        post_dt = datetime.fromisoformat(post["acquisition_time"].replace("Z", "+00:00"))
        for p in dated[1:]:
            d = datetime.fromisoformat(p["acquisition_time"].replace("Z", "+00:00"))
            if (post_dt - d).days >= 20:
                pre = p
                break
        if pre is None and len(dated) > 1:
            pre = dated[-1]
    except Exception:
        pre = dated[-1] if len(dated) > 1 else None
    return post, pre


def run_live_analysis(bbox: list[float] | None = None,
                      force: bool = False) -> dict:
    """Full LIVE pipeline with staged progress. Returns steps + summary.

    If no observation newer than the last analysis exists (and not forced),
    returns {"up_to_date": True} and keeps existing analysis (no fake churn).
    """
    bbox = bbox or cfg.STUDY_AREA["bbox"]
    steps: list[str] = []
    errors: list[str] = []

    def step(text: str) -> None:
        steps.append(text)
        db.add_audit(text)

    step("Satellite search started.")
    # ---- Sentinel-1 search ----
    step("Searching for new Sentinel-1 imagery...")
    try:
        s1 = s1mod.search(bbox)
        db.add_audit(f"New Sentinel-1 product found: "
                     f"{(s1['products'][0]['product_id'] if s1['products'] else 'none')}.")
    except Exception as exc:
        errors.append(str(exc))
        _mark_source("sentinel1", "unavailable", f"Sentinel-1 unavailable: {exc}")
        step("Sentinel-1 unavailable — cannot run live analysis.")
        return {"ok": False, "up_to_date": False, "steps": steps, "errors": errors}
    if not s1["products"]:
        step("No Sentinel-1 products cover this area/date range.")
        return {"ok": False, "up_to_date": True, "steps": steps, "errors": errors}

    post, pre = _pick_pre_post(s1["products"])
    last_s1 = db.get_state("last_analysis_s1", "")
    if post and post["product_id"] == last_s1 and not force:
        step("No newer satellite observation available. Existing analysis retained.")
        return {"ok": True, "up_to_date": True, "steps": steps, "errors": errors,
                "s1_product": post["product_id"]}

    # ---- cache products ----
    with db.get_conn() as conn:
        for p in s1["products"][:4]:
            s1mod.cache_product(p)
            db.upsert_product(conn, p)

    # ---- previews ----
    step("Retrieving Sentinel-1 preview imagery...")
    try:
        post_path = s1mod.fetch_preview(post)
        pre_path = s1mod.fetch_preview(pre) if pre else None
        step("Sentinel-1 processed.")
    except Exception as exc:
        errors.append(str(exc))
        _mark_source("sentinel1", "unavailable", f"Preview retrieval failed: {exc}")
        step("Sentinel-1 preview unavailable — analysis aborted.")
        return {"ok": False, "up_to_date": False, "steps": steps, "errors": errors}

    # ---- Sentinel-2 (supporting; optional) ----
    step("Searching Sentinel-2 (cloud-filtered) for supporting evidence...")
    s2_product, s2_scene = None, None
    try:
        s2 = s2mod.search(bbox)
        if s2["products"]:
            s2_product = s2["products"][0]
            with db.get_conn() as conn:
                s2mod.cache_product(s2_product)
                db.upsert_product(conn, s2_product)
            s2_path = s2mod.fetch_preview(s2_product)
            s2_scene = anamod.analyse_scene(
                s2_path, anamod._scene_bbox(s2_product.get("bbox"), bbox), bbox,
                cfg.GRID_ROWS, cfg.GRID_COLS, optical=True)
            step(f"Sentinel-2 processed (cloud "
                 f"{(s2_product.get('cloud_cover') if s2_product.get('cloud_cover') is not None else '?')}%).")
            _mark_source("sentinel2", "connected",
                         f"Supporting evidence; cloud {s2_product.get('cloud_cover')}%",
                         acquisition=s2_product.get("acquisition_time"))
        else:
            step("No sufficiently clear Sentinel-2 scene — continuing with Sentinel-1.")
            _mark_source("sentinel2", "unavailable", "No clear scene (cloud filter).")
    except Exception as exc:
        errors.append(f"Sentinel-2: {exc}")
        step("Sentinel-2 unavailable — continuing with Sentinel-1.")
        _mark_source("sentinel2", "unavailable", f"Sentinel-2 unavailable: {exc}")

    # ---- per-zone analysis + fusion ----
    step("Processing flood extent per zone...")
    post_scene = anamod.analyse_scene(
        post_path, anamod._scene_bbox(post.get("bbox"), bbox), bbox,
        cfg.GRID_ROWS, cfg.GRID_COLS)
    pre_scene = (anamod.analyse_scene(
        pre_path, anamod._scene_bbox(pre.get("bbox"), bbox), bbox,
        cfg.GRID_ROWS, cfg.GRID_COLS) if pre_path else None)
    metrics = anamod.fuse(post_scene, pre_scene, s2_scene)
    analysis_id = f"A-{uuid.uuid4().hex[:8]}"
    anamod.write_analysis(analysis_id, {
        "mode": "live",
        "s1_product": post["product_id"],
        "s1_pre_product": pre["product_id"] if pre else None,
        "s2_product": s2_product["product_id"] if s2_product else None,
        "bbox": bbox, "metrics": metrics,
    })
    step("Flood analysis completed.")
    apply_live_metrics(metrics, analysis_id, post, s2_product)
    step(f"Analysis completed. {len(metrics)} zones updated.")
    db.add_audit(f"GHS recalculated from live satellite analysis {analysis_id}.")
    version = bump_data_version(f"live analysis {analysis_id}")
    emit("satellite_updated", {"analysis_id": analysis_id, "zones_updated": len(metrics)})
    emit("zones_updated", {"data_version": version})
    return {"ok": True, "up_to_date": False, "steps": steps, "errors": errors,
            "analysis_id": analysis_id, "zones_updated": len(metrics),
            "s1_product": post["product_id"],
            "s1_pre_product": pre["product_id"] if pre else None,
            "s2_product": s2_product["product_id"] if s2_product else None}


def apply_live_metrics(metrics: dict, analysis_id: str,
                       post: dict, s2_product: dict | None) -> None:
    """Write satellite-derived severity/flood/confidence into zones (no random)."""
    now = db.now_iso()
    with db.get_conn() as conn:
        for zid, m in metrics.items():
            z = conn.execute("SELECT * FROM zones WHERE zone_id=?", (zid,)).fetchone()
            if not z:
                continue
            conn.execute("UPDATE zones SET severity=?, flood_extent=?, last_updated=? "
                         "WHERE zone_id=?",
                         (m["flood_severity"], m["flood_extent"], now, zid))
            db.upsert_zone_metrics(conn, {"zone_id": zid,
                                          "flood_extent": m["flood_extent"],
                                          "flood_severity": m["flood_severity"],
                                          "change_score": m["change_score"],
                                          "satellite_confidence": m["satellite_confidence"],
                                          "evidence": m["evidence"],
                                          "analysis_id": analysis_id})
        db.record_analysis(conn, {
            "analysis_id": analysis_id, "created_at": now, "mode": "live",
            "s1_product": post["product_id"],
            "s1_pre_product": None, "s2_product": s2_product["product_id"] if s2_product else None,
            "zones_updated": len(metrics),
            "detail": "Prototype SAR Flood Detection from open STAC previews.",
        })
    _mark_source("sentinel1", "connected",
                 f"Prototype SAR Flood Detection; {post['product_id']}",
                 acquisition=post.get("acquisition_time"))
    db.set_state("last_analysis_s1", post["product_id"])
    db.set_state("last_analysis_at", now)


def _mark_source(source_id: str, status: str, detail: str,
                 acquisition: str | None = None) -> None:
    now = db.now_iso()
    with db.get_conn() as conn:
        cur = {r["source_id"]: r for r in db.get_sources()}.get(source_id, {})
        cur.update(source_id=source_id, status=status, detail=detail,
                   last_updated=now, last_checked=now)
        if acquisition:
            cur["acquisition_time"] = acquisition
        if status in ("connected", "demo"):
            cur["last_successful_update"] = now
            if source_id in ("sentinel1", "sentinel2"):
                cur["processing_time"] = now
        db.upsert_source(conn, cur)


def get_status() -> dict:
    """Freshness truth for smart frontend polling + header badge logic."""
    sources = {s["source_id"]: s for s in db.get_sources()}
    now = datetime.now(timezone.utc)
    per_source: dict[str, dict] = {}
    for sid, s in sources.items():
        last_ok = s.get("last_successful_update")
        age_min = None
        if last_ok:
            try:
                age_min = (now - datetime.fromisoformat(last_ok)).total_seconds() / 60
            except Exception:
                pass
        state = s.get("status", "demo")
        if state == "demo":
            freshness = "demo"
        elif state == "unavailable":
            freshness = "unavailable"
        elif age_min is not None and age_min <= cfg.FRESHNESS_MINUTES:
            freshness = "fresh"
        else:
            freshness = "stale"
        per_source[sid] = {"status": state, "freshness": freshness,
                           "age_min": round(age_min, 1) if age_min is not None else None,
                           "last_checked": s.get("last_checked"),
                           "last_successful_update": last_ok,
                           "acquisition_time": s.get("acquisition_time"),
                           "processing_time": s.get("processing_time")}
    live_ok = any(per_source.get(k, {}).get("freshness") == "fresh"
                  for k in ("sentinel1", "sentinel2", "osm"))
    any_live_attempt = cfg.APP_MODE == "live" or live_ok
    if not any_live_attempt and all(v.get("status") == "demo" for v in sources.values()):
        overall = "demo"
    elif live_ok:
        overall = "live"
    elif any(v.get("status") == "unavailable" for v in sources.values()) and not live_ok and cfg.APP_MODE == "live":
        overall = "unavailable"
    else:
        overall = "stale" if cfg.APP_MODE == "live" else "demo"
    return {"mode": cfg.APP_MODE, "overall": overall,
            "data_version": db.get_state("data_version", ""),
            "zones_updated_at": db.get_state("zones_updated_at", ""),
            "last_satellite_check": db.get_state("last_satellite_check", ""),
            "sources": per_source}


# ================= automatic satellite checking =================
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()


def check_for_new_imagery() -> dict:
    """Scheduler tick: look for products newer than the last analysis."""
    db.set_state("last_satellite_check", db.now_iso())
    try:
        s1 = s1mod.search()
        if not s1["products"]:
            return {"checked": True, "new": False}
        newest = max((p.get("acquisition_time") or "") for p in s1["products"])
        if newest and newest != db.get_state("last_analysis_s1", "") and cfg.APP_MODE == "live":
            result = run_live_analysis()
            return {"checked": True, "new": True, "result": result}
        return {"checked": True, "new": False}
    except Exception as exc:
        db.add_audit(f"Scheduled satellite check failed: {exc}")
        return {"checked": False, "new": False, "error": str(exc)}


def _scheduler_loop() -> None:
    interval = max(15, cfg.SATELLITE_REFRESH_MINUTES) * 60
    while not _scheduler_stop.wait(interval):
        try:
            check_for_new_imagery()
        except Exception:
            pass


def start_scheduler() -> bool:
    """Start background satellite checker (not under pytest)."""
    global _scheduler_thread
    if (not cfg.SATELLITE_SCHEDULER_ENABLED or "pytest" in sys.modules
            or (_scheduler_thread and _scheduler_thread.is_alive())):
        return False
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True,
                                         name="gh-sat-scheduler")
    _scheduler_thread.start()
    return True
