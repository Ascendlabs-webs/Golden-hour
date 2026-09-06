"""All REST endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config as cfg
from .. import database as db
from ..demo import chennai as demo
from ..gis import zones as geom
from ..models.schemas import DispatchIn, OverrideIn, ReportIn
from ..processing import pipeline as pipe
from ..scoring import ghs as scoring
from ..satellite import flood as floodmod
from ..satellite import sentinel1 as s1mod
from ..satellite import sentinel2 as s2mod
from ..satellite.sentinel import gee_status

router = APIRouter()


class SatelliteSearchIn(BaseModel):
    bbox: list[float] | None = None
    start_date: str = "2026-08-01"
    end_date: str = "2026-09-06"
    cloud_max: float = 40


class FloodAnalysisIn(BaseModel):
    bbox: list[float] | None = None
    force: bool = False


class VerifyIn(BaseModel):
    verifier: str = "operator"


def _enrich(zone: dict, t_min: float = 0) -> dict:
    s = pipe.score_zone_record(zone, t_min)
    out = dict(zone)
    out["manual_override"] = bool(zone.get("manual_override", False))
    out.update(s)
    return out


@router.get("/health")
def health():
    zones = db.get_zones()
    return {
        "status": "ok",
        "mode": cfg.APP_MODE,
        "study_area": cfg.STUDY_AREA["name"],
        "zones": len(zones),
        "reports": len(db.get_reports()),
        "teams": len(db.get_teams()),
    }


@router.get("/config")
def get_config():
    return {
        "app_mode": cfg.APP_MODE,
        "study_area": cfg.STUDY_AREA,
        "study_area_presets": list(cfg.STUDY_AREA_PRESETS.keys()),
        "grid": {"rows": cfg.GRID_ROWS, "cols": cfg.GRID_COLS},
        "ghs_weights": dict(pipe.cfg.GHS_WEIGHTS),
        "damage_weights": dict(pipe.cfg.DAMAGE_WEIGHTS),
        "incident_profiles": dict(pipe.cfg.INCIDENT_PROFILES),
        "priority_thresholds": dict(pipe.cfg.PRIORITY_THRESHOLDS),
        "confidence_thresholds": {
            "high": cfg.CONF_THRESHOLD_HIGH,
            "moderate": cfg.CONF_THRESHOLD_MODERATE,
            "medium": cfg.CONF_THRESHOLD_MEDIUM,
        },
        "satellite_refresh_minutes": cfg.SATELLITE_REFRESH_MINUTES,
        "disclaimer": ("GoldenHour AI is an academic/research prototype. Golden Hour "
                       "Score is a disaster-response prioritization heuristic, not a "
                       "medically validated survival prediction."),
    }


@router.get("/status")
def status():
    """Freshness truth: lets the frontend reload only when data is newer."""
    return pipe.get_status()


# ---- zones ----
@router.get("/zones")
def list_zones(t_min: float = 0):
    return [_enrich(z, t_min) for z in db.get_zones()]


@router.get("/zones/geojson")
def zones_geojson(t_min: float = 0, mode: str = "priority"):
    features = []
    for z in db.get_zones():
        s = pipe.score_zone_record(z, t_min)
        if mode == "damage":
            value = z.get("severity", 0)
            cls, score = scoring.classify(value), int(value)
        elif mode == "confidence":
            value = z.get("confidence", 0)
            cls, score = scoring.classify(value), int(value)
        elif mode == "flood":
            value = float(z.get("flood_extent", 0) or 0) * 100
            cls, score = scoring.classify(value), int(round(value))
        elif mode == "population":
            value = z.get("population_risk", 0)
            cls, score = scoring.classify(value), int(value)
        elif mode == "accessibility":
            value = z.get("accessibility", 0)
            cls, score = scoring.classify(value), int(value)
        else:
            cls, score = s["priority_class"], s["golden_hour_score"]
        feat = geom.zone_feature(z, cfg.STUDY_AREA["bbox"], cfg.GRID_ROWS, cfg.GRID_COLS, score, cls)
        feat["properties"]["urgency"] = s["urgency"]
        feat["properties"]["breakdown"] = s["breakdown"]
        feat["properties"]["silent_zone"] = s["silent_zone"]
        feat["properties"]["flood_extent_percent"] = round(float(z.get("flood_extent", 0) or 0) * 100, 1)
        features.append(feat)
    return geom.feature_collection(features)


@router.get("/zones/projections")
def projections():
    out = []
    for z in db.get_zones():
        row = {"zone_id": z["zone_id"], "neighbourhood": z.get("neighbourhood"),
               "incident_type": z.get("incident_type")}
        for t in (0, 15, 30, 60):
            key = "now" if t == 0 else f"t{t}"
            row[key] = pipe.score_zone_record(z, t)["golden_hour_score"]
        out.append(row)
    out.sort(key=lambda r: r["now"], reverse=True)
    return out[:12]


@router.get("/zones/{zone_id}")
def get_zone(zone_id: str, t_min: float = 0):
    z = db.get_zone(zone_id)
    if not z:
        raise HTTPException(404, f"Unknown zone {zone_id}")
    enriched = _enrich(z, t_min)
    metrics = db.get_zone_metrics().get(zone_id)
    if metrics and metrics.get("analysis_id"):
        enriched["satellite_metrics"] = {
            "flood_extent_percent": round(float(metrics.get("flood_extent", 0)) * 100, 1),
            "flood_severity": metrics.get("flood_severity"),
            "change_score": metrics.get("change_score"),
            "satellite_confidence": metrics.get("satellite_confidence"),
            "evidence": json.loads(metrics.get("evidence") or "[]"),
            "analysis_id": metrics.get("analysis_id"),
            "updated_at": metrics.get("updated_at"),
            "method": "Prototype SAR Flood Detection (open STAC previews)",
        }
    else:
        fa = floodmod.analyze_zone(zone_id)
        fa["method"] = "Prototype SAR Flood Detection (demo values)"
        enriched["flood_analysis"] = fa
    zone_reports = [r for r in db.get_reports() if r["zone_id"] == zone_id]
    enriched["evidence_sources"] = {
        "sentinel1": bool(metrics),
        "sentinel2": bool(metrics and "sentinel-2" in (json.loads(metrics.get("evidence") or "[]"))),
        "openstreetmap": True,
        "population": True,
        "crowdsourced_reports": len(zone_reports),
    }
    return enriched


@router.post("/zones/{zone_id}/override")
def override_zone(zone_id: str, body: OverrideIn):
    z = db.get_zone(zone_id)
    if not z:
        raise HTTPException(404, f"Unknown zone {zone_id}")
    db.set_override(zone_id, body.overridden)
    action = "applied to" if body.overridden else "removed from"
    db.add_audit(f"Human override {action} {zone_id}.")
    pipe.emit("override_changed", {"zone_id": zone_id, "manual_override": body.overridden})
    pipe.bump_data_version(f"override {zone_id}")
    return {"zone_id": zone_id, "manual_override": body.overridden}


# ---- reports ----
THRESHOLDS = {"high": cfg.CONF_THRESHOLD_HIGH, "moderate": cfg.CONF_THRESHOLD_MODERATE,
              "medium": cfg.CONF_THRESHOLD_MEDIUM}
LEGACY_LABELS = {"Verified": "High Confidence", "High Confidence": "Moderate Confidence",
                 "Duplicate": "Potential Duplicate"}


@router.get("/reports")
def list_reports(status: Optional[str] = None, sort: str = "confidence"):
    reps = db.get_reports()
    if status and status != "All":
        # accept legacy labels from older clients
        want = {status, LEGACY_LABELS.get(status, status)}
        reps = [r for r in reps if r["status"] in want]
    if sort == "time":
        reps.sort(key=lambda r: r.get("timestamp", ""))
    else:
        reps.sort(key=lambda r: r.get("score", 0), reverse=True)
    return reps


@router.post("/reports", status_code=201)
def create_report(body: ReportIn):
    z = db.get_zone(body.zone_id)
    if not z:
        raise HTTPException(404, f"Unknown zone {body.zone_id}")
    existing = [r for r in db.get_reports() if r["zone_id"] == body.zone_id]
    ts = datetime.now(timezone.utc).isoformat()
    new = {"zone_id": body.zone_id, "incident_type": body.incident_type, "timestamp": ts}
    dup = scoring.detect_duplicate(new, existing)
    # Heuristic evidence flags for a fresh crowdsourced report.
    nearby = len(existing) >= 2
    score, label = scoring.score_report(
        multiple_nearby=nearby, recent=True, location_consistent=True,
        supporting_evidence=False, is_duplicate=dup, thresholds=THRESHOLDS)
    rid = db.next_report_id()
    record = {
        "report_id": rid, "zone_id": body.zone_id, "incident_type": body.incident_type,
        "latitude": body.latitude, "longitude": body.longitude,
        "description": body.description, "timestamp": ts, "source": body.source,
        "multiple_nearby": nearby, "recent_timestamp": True,
        "location_consistent": True, "supporting_evidence": False,
        "is_duplicate": dup, "score": score, "status": label,
    }
    with db.get_conn() as conn:
        db.insert_report(conn, record)
        # bump zone report count + refresh confidence slightly
        cur = conn.execute("SELECT reports_count FROM zones WHERE zone_id=?", (body.zone_id,)).fetchone()
        conn.execute("UPDATE zones SET reports_count=?, last_updated=? WHERE zone_id=?",
                     (int(cur["reports_count"] or 0) + 1, db.now_iso(), body.zone_id))
    db.add_audit(f"Report #{rid} received for {body.zone_id}" +
                 (" — flagged as potential duplicate." if dup else "."))
    pipe.emit("report_received", {"report_id": rid, "zone_id": body.zone_id})
    pipe.bump_data_version(f"report {rid}")
    return record


@router.post("/reports/{report_id}/verify", status_code=200)
def verify_report(report_id: int, body: VerifyIn):
    """Explicit human verification — the ONLY path to 'Human Verified'."""
    updated = db.verify_report(report_id, body.verifier)
    if not updated:
        raise HTTPException(404, f"Unknown report {report_id}")
    db.add_audit(f"Human verification performed on report #{report_id} by {body.verifier}.")
    pipe.emit("report_received", {"report_id": report_id, "verified": True})
    pipe.bump_data_version(f"verify {report_id}")
    return updated


# ---- teams ----
@router.get("/teams")
def list_teams():
    return db.get_teams()


@router.post("/teams/{team_id}/dispatch")
def dispatch_team(team_id: int, body: DispatchIn | None = None):
    teams = db.get_teams()
    team = next((t for t in teams if t["team_id"] == team_id), None)
    if not team:
        raise HTTPException(404, f"Unknown team {team_id}")
    if team["status"] != "Available":
        raise HTTPException(409, f"{team['name']} is not available (status={team['status']}).")
    target_id = (body.zone_id if body and body.zone_id else None)
    if not target_id:
        assigned = {t["assigned_zone"] for t in teams if t.get("assigned_zone")}
        ranked = sorted((_enrich(z) for z in db.get_zones()),
                        key=lambda z: z["golden_hour_score"], reverse=True)
        target = next((z for z in ranked if z["zone_id"] not in assigned), None)
        if not target:
            raise HTTPException(409, "No unassigned priority zones remaining.")
        target_id = target["zone_id"]
    updated = db.dispatch_team(team_id, target_id)
    ghs = pipe.score_zone_record(db.get_zone(target_id))["golden_hour_score"]
    db.add_audit(f"{team['name']} dispatched to {target_id} — Golden Hour Score {ghs}.")
    pipe.emit("team_dispatched", {"team_id": team_id, "zone_id": target_id})
    pipe.bump_data_version(f"dispatch {team_id}")
    return {**updated, "target_ghs": ghs}


# ---- analytics ----
@router.get("/analytics")
def analytics():
    zones = [_enrich(z) for z in db.get_zones()]
    reports = db.get_reports()
    teams = db.get_teams()
    by_class = {c: 0 for c in ("Critical", "High", "Medium", "Low")}
    for z in zones:
        by_class[z["priority_class"]] = by_class.get(z["priority_class"], 0) + 1
    by_status: dict[str, int] = {}
    for r in reports:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    total_exp = sum(int(z.get("estimated_population", 0) or 0) for z in zones)
    flood_area = round(sum(float(z.get("flood_extent", 0) or 0) for z in zones) / max(len(zones), 1), 3)
    # Rough affected-area estimate: mean flood fraction × study bbox area.
    min_lon, min_lat, max_lon, max_lat = cfg.STUDY_AREA["bbox"]
    bbox_km2 = abs(max_lon - min_lon) * 109.0 * abs(max_lat - min_lat) * 111.0
    return {
        "priority_distribution": [{"name": k, "count": v} for k, v in by_class.items()],
        "report_status": [{"name": k, "value": v} for k, v in by_status.items() if v],
        "estimated_exposed_population": total_exp,
        "mean_flood_extent": flood_area,
        "affected_area_km2": round(bbox_km2 * flood_area, 1),
        "affected_zones": sum(1 for z in zones if float(z.get("flood_extent", 0) or 0) > 0.3),
        "critical_zones": by_class.get("Critical", 0),
        "high_priority_zones": by_class.get("High", 0),
        "reports_received": len(reports),
        "high_confidence_reports": sum(1 for r in reports if r["status"] in ("High Confidence", "Human Verified")),
        "potential_duplicates": sum(1 for r in reports if r["status"] == "Potential Duplicate"),
        "human_verified_reports": sum(1 for r in reports if r.get("human_verified")),
        "under_reported_zones": [z["zone_id"] for z in zones if z["silent_zone"]],
        "teams_available": len([t for t in teams if t["status"] == "Available"]),
        "teams_dispatched": len([t for t in teams if t["status"] != "Available"]),
        "silent_zones": [z["zone_id"] for z in zones if z["silent_zone"]],
        "blocked_roads_estimate": 10 + sum(1 for z in zones if float(z.get("flood_extent", 0)) > 0.5),
    }


@router.get("/data-sources")
def data_sources():
    sources = db.get_sources()
    return {"sources": sources, "gee": gee_status(), "mode": cfg.APP_MODE}


@router.get("/audit")
def audit_log(limit: int = 20):
    return db.get_audit(limit)


@router.post("/ingest/refresh")
def ingest_refresh(mode: str = Query("demo", pattern="^(demo|live)$")):
    if mode == "live":
        summary = pipe.refresh_live()
    else:
        summary = pipe.refresh_demo()
        db.add_audit("Manual recalculation triggered — reports, confidence and urgency refreshed.")
    return {"ok": True, "mode": mode, **summary}


# ---- satellite search / analysis ----
@router.post("/satellite/search")
def satellite_search(body: SatelliteSearchIn):
    """Real open-catalogue search (Planetary Computer STAC, Copernicus fallback)."""
    bbox = body.bbox or cfg.STUDY_AREA["bbox"]
    out: dict = {"bbox": bbox}
    errors: list[str] = []
    try:
        s1 = s1mod.search(bbox, body.start_date, body.end_date)
        out["sentinel1"] = s1
        with db.get_conn() as conn:
            for p in s1["products"][:5]:
                db.upsert_product(conn, p)
    except Exception as exc:
        errors.append(f"Sentinel-1: {exc}")
        out["sentinel1"] = {"count": 0, "products": [], "error": str(exc)}
    try:
        s2 = s2mod.search(bbox, body.start_date, body.end_date, body.cloud_max)
        out["sentinel2"] = s2
        with db.get_conn() as conn:
            for p in s2["products"][:5]:
                db.upsert_product(conn, p)
    except Exception as exc:
        errors.append(f"Sentinel-2: {exc}")
        out["sentinel2"] = {"count": 0, "products": [], "error": str(exc)}
    db.add_audit(f"Satellite search completed: "
                 f"{out['sentinel1'].get('count', 0)} S1 / "
                 f"{out['sentinel2'].get('count', 0)} S2 products.")
    db.set_state("last_satellite_check", db.now_iso())
    out["errors"] = errors
    return out


@router.post("/analysis/flood")
def analysis_flood(body: FloodAnalysisIn):
    """Run the live flood pipeline: search -> cache -> process -> zones -> GHS."""
    return pipe.run_live_analysis(body.bbox, force=body.force)


@router.get("/satellite/products")
def satellite_products(satellite: Optional[str] = None):
    return {"products": db.get_products(satellite), "analyses": db.get_analyses()}


@router.get("/satellite/preview/{product_id}")
def satellite_preview(product_id: str):
    """Serve a cached preview render (real imagery). 404 if not cached."""
    for directory in (cfg.S1_RAW_DIR, cfg.S2_RAW_DIR):
        for p in directory.glob("*.preview.png"):
            if product_id in p.name:
                return FileResponse(str(p), media_type="image/png")
    raise HTTPException(404, "Satellite preview unavailable for this zone.")


# ---- study areas ----
@router.get("/study-areas")
def study_areas():
    return {"active": cfg.STUDY_AREA, "presets": cfg.STUDY_AREA_PRESETS}


@router.post("/study-areas/{name}/activate")
def activate_study_area(name: str):
    preset = cfg.STUDY_AREA_PRESETS.get(name)
    if not preset:
        raise HTTPException(404, f"Unknown study area {name}")
    cfg.STUDY_AREA.update(name=name, country=preset["country"],
                          latitude=preset["latitude"], longitude=preset["longitude"],
                          bbox=list(preset["bbox"]))
    summary = pipe.refresh_demo()  # deterministic reseed for the new bbox
    db.add_audit(f"Study area switched to {name} — demo scenario rebuilt.")
    return {"ok": True, "study_area": cfg.STUDY_AREA, **summary}
