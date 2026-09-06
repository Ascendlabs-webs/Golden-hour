"""API + GeoJSON + override + dispatch tests (isolated temp SQLite DB)."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["APP_MODE"] = "demo"

from backend.app import database as db  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.processing import pipeline as pipe  # noqa: E402

db.configure(_tmp.name)
db.init_db()
pipe.refresh_demo()

client = TestClient(create_app())


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["zones"] == 36


def test_zones_have_scores():
    zones = client.get("/api/zones").json()
    assert len(zones) == 36
    z = zones[0]
    for key in ("golden_hour_score", "priority_class", "breakdown", "values", "silent_zone"):
        assert key in z
    assert 0 <= z["golden_hour_score"] <= 100
    assert z["priority_class"] in ("Critical", "High", "Medium", "Low")


def test_geojson_structure():
    gj = client.get("/api/zones/geojson").json()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 36
    f = gj["features"][0]
    assert f["geometry"]["type"] == "Polygon"
    props = f["properties"]
    for key in ("zone_id", "golden_hour_score", "priority_class", "severity",
                "population_risk", "vulnerability", "accessibility", "confidence"):
        assert key in props


def test_projections_shape():
    proj = client.get("/api/zones/projections").json()
    assert len(proj) > 0
    assert set(("zone_id", "now", "t15", "t30", "t60")) <= set(proj[0].keys())


def test_override_roundtrip():
    r = client.post("/api/zones/Z-001/override", json={"overridden": True})
    assert r.status_code == 200
    z = client.get("/api/zones/Z-001").json()
    assert z["manual_override"] is True
    assert z["priority_class"] == "Critical"  # human override wins
    r = client.post("/api/zones/Z-001/override", json={"overridden": False})
    assert r.status_code == 200
    z = client.get("/api/zones/Z-001").json()
    assert z["manual_override"] is False


def test_override_unknown_zone_404():
    assert client.post("/api/zones/Z-999/override", json={"overridden": True}).status_code == 404


def test_report_flow_and_duplicate_flag():
    body = {"zone_id": "Z-005", "incident_type": "Medical Emergency",
            "latitude": 13.1, "longitude": 80.25, "description": "test"}
    r1 = client.post("/api/reports", json=body)
    assert r1.status_code == 201
    r2 = client.post("/api/reports", json=body)  # same zone+type, fresh -> duplicate
    assert r2.status_code == 201
    assert r2.json()["status"] == "Potential Duplicate"


def test_dispatch_and_no_double_dispatch():
    teams = client.get("/api/teams").json()
    avail = next(t for t in teams if t["status"] == "Available")
    r = client.post(f"/api/teams/{avail['team_id']}/dispatch", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "Dispatched"
    r2 = client.post(f"/api/teams/{avail['team_id']}/dispatch", json={})
    assert r2.status_code == 409


def test_audit_log_records_actions():
    logs = db.get_audit(50)
    texts = " ".join(l["text"] for l in logs)
    assert "override" in texts or "dispatched" in texts or "Report" in texts


def test_data_sources_present():
    ds = client.get("/api/data-sources").json()
    ids = {s["source_id"] for s in ds["sources"]}
    assert {"sentinel1", "sentinel2", "osm", "population", "engine"} <= ids


def test_analytics_shape():
    a = client.get("/api/analytics").json()
    assert "priority_distribution" in a
    assert "report_status" in a
    assert a["estimated_exposed_population"] > 0
    for key in ("affected_area_km2", "affected_zones", "critical_zones",
                "reports_received", "potential_duplicates", "under_reported_zones"):
        assert key in a


def test_human_verification_flow():
    body = {"zone_id": "Z-006", "incident_type": "Property Damage",
            "latitude": 13.1, "longitude": 80.25, "description": "verify me"}
    rid = client.post("/api/reports", json=body).json()["report_id"]
    r = client.post(f"/api/reports/{rid}/verify", json={"verifier": "officer-k"})
    assert r.status_code == 200
    assert r.json()["status"] == "Human Verified"
    assert r.json()["verified_by"] == "officer-k"
    assert client.post("/api/reports/999999/verify", json={}).status_code == 404


def test_status_shape():
    s = client.get("/api/status").json()
    assert s["mode"] in ("demo", "live")
    assert s["overall"] in ("demo", "live", "stale", "unavailable")
    assert "sources" in s and "sentinel1" in s["sources"]


def test_satellite_search_offline_graceful(monkeypatch=None):
    # Real call may succeed (network) or fail gracefully — both acceptable.
    r = client.post("/api/satellite/search", json={
        "bbox": [80.05, 12.90, 80.32, 13.25],
        "start_date": "2026-08-01", "end_date": "2026-09-06", "cloud_max": 40})
    assert r.status_code == 200
    body = r.json()
    assert "sentinel1" in body and "sentinel2" in body and "errors" in body


def test_satellite_preview_404():
    assert client.get("/api/satellite/preview/NOPE-NOT-CACHED").status_code == 404


def test_study_areas():
    areas = client.get("/api/study-areas").json()
    assert "Chennai" in areas["presets"]
    assert areas["active"]["name"] in ("Chennai", "Mumbai", "Bengaluru",
                                       "Hyderabad", "Delhi", "Kolkata")
    assert client.post("/api/study-areas/Atlantis/activate").status_code == 404


def test_zone_detail_evidence():
    z = client.get("/api/zones/Z-001").json()
    assert "evidence_sources" in z
    assert "crowdsourced_reports" in z["evidence_sources"]
