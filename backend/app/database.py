"""SQLite persistence (stdlib sqlite3 — zero extra dependencies)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import resolve_db_path

_lock = threading.Lock()
_db_path: Optional[Path] = None


def configure(path: Path | str | None = None) -> Path:
    global _db_path
    _db_path = Path(path) if path else resolve_db_path()
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    return _db_path


def _path() -> Path:
    return _db_path or configure()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT PRIMARY KEY,
    neighbourhood TEXT,
    row INTEGER, col INTEGER,
    latitude REAL, longitude REAL,
    severity REAL, population_risk REAL, vulnerability REAL,
    accessibility REAL, confidence REAL,
    reports_count INTEGER DEFAULT 0,
    incident_type TEXT,
    flood_extent REAL DEFAULT 0,
    estimated_population INTEGER DEFAULT 0,
    manual_override INTEGER DEFAULT 0,
    last_updated TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    report_id INTEGER PRIMARY KEY,
    zone_id TEXT,
    incident_type TEXT,
    latitude REAL, longitude REAL,
    description TEXT,
    timestamp TEXT,
    source TEXT DEFAULT 'crowdsourced',
    multiple_nearby INTEGER DEFAULT 0,
    recent_timestamp INTEGER DEFAULT 0,
    location_consistent INTEGER DEFAULT 0,
    supporting_evidence INTEGER DEFAULT 0,
    is_duplicate INTEGER DEFAULT 0,
    human_verified INTEGER DEFAULT 0,
    verified_by TEXT,
    verified_at TEXT,
    score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Low Confidence'
);
CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT DEFAULT 'Available',
    capacity INTEGER DEFAULT 4,
    current_lat REAL, current_lon REAL,
    assigned_zone TEXT,
    eta_min INTEGER DEFAULT 15
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    text TEXT
);
CREATE TABLE IF NOT EXISTS data_sources (
    source_id TEXT PRIMARY KEY,
    category TEXT,
    display_name TEXT,
    status TEXT DEFAULT 'demo',
    last_updated TEXT,
    last_checked TEXT,
    last_successful_update TEXT,
    acquisition_time TEXT,
    processing_time TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS overrides (
    zone_id TEXT PRIMARY KEY,
    overridden INTEGER DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS satellite_products (
    product_id TEXT PRIMARY KEY,
    satellite TEXT,
    provider TEXT,
    collection TEXT,
    acquisition_time TEXT,
    cloud_cover REAL,
    preview_href TEXT,
    preview_cached INTEGER DEFAULT 0,
    bbox TEXT,
    searched_at TEXT
);
CREATE TABLE IF NOT EXISTS satellite_analysis (
    analysis_id TEXT PRIMARY KEY,
    created_at TEXT,
    mode TEXT DEFAULT 'live',
    s1_product TEXT,
    s1_pre_product TEXT,
    s2_product TEXT,
    zones_updated INTEGER DEFAULT 0,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS zone_metrics (
    zone_id TEXT PRIMARY KEY,
    flood_extent REAL DEFAULT 0,
    flood_severity REAL DEFAULT 0,
    change_score REAL DEFAULT 0,
    satellite_confidence REAL DEFAULT 0,
    evidence TEXT DEFAULT '[]',
    analysis_id TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db(path: Path | str | None = None) -> Path:
    p = configure(path)
    with _lock, get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    return p


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns/tables missing from older databases (idempotent)."""
    def cols(table: str) -> set[str]:
        try:
            return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except Exception:
            return set()
    for table, col, decl in [
        ("data_sources", "last_checked", "TEXT"),
        ("data_sources", "last_successful_update", "TEXT"),
        ("data_sources", "acquisition_time", "TEXT"),
        ("data_sources", "processing_time", "TEXT"),
        ("reports", "human_verified", "INTEGER DEFAULT 0"),
        ("reports", "verified_by", "TEXT"),
        ("reports", "verified_at", "TEXT"),
    ]:
        if table in ("data_sources", "reports") and col not in cols(table):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except Exception:
                pass


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---- zones ----
def upsert_zone(conn: sqlite3.Connection, z: dict) -> None:
    conn.execute(
        """INSERT INTO zones (zone_id, neighbourhood, row, col, latitude, longitude,
            severity, population_risk, vulnerability, accessibility, confidence,
            reports_count, incident_type, flood_extent, estimated_population,
            manual_override, last_updated)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(zone_id) DO UPDATE SET
            neighbourhood=excluded.neighbourhood, row=excluded.row, col=excluded.col,
            latitude=excluded.latitude, longitude=excluded.longitude,
            severity=excluded.severity, population_risk=excluded.population_risk,
            vulnerability=excluded.vulnerability, accessibility=excluded.accessibility,
            confidence=excluded.confidence, reports_count=excluded.reports_count,
            incident_type=excluded.incident_type, flood_extent=excluded.flood_extent,
            estimated_population=excluded.estimated_population,
            manual_override=excluded.manual_override, last_updated=excluded.last_updated""",
        (z["zone_id"], z.get("neighbourhood"), z.get("row"), z.get("col"),
         z.get("latitude"), z.get("longitude"), z.get("severity"),
         z.get("population_risk"), z.get("vulnerability"), z.get("accessibility"),
         z.get("confidence"), z.get("reports_count", 0), z.get("incident_type"),
         z.get("flood_extent", 0), z.get("estimated_population", 0),
         int(bool(z.get("manual_override", False))), z.get("last_updated", now_iso())),
    )


def get_zones() -> list[dict]:
    with get_conn() as conn:
        return [_row_to_dict(r) for r in conn.execute("SELECT * FROM zones ORDER BY zone_id")]


def get_zone(zone_id: str) -> Optional[dict]:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM zones WHERE zone_id=?", (zone_id,)).fetchone()
        return _row_to_dict(r) if r else None


def set_override(zone_id: str, overridden: bool) -> None:
    with _lock, get_conn() as conn:
        conn.execute("UPDATE zones SET manual_override=?, last_updated=? WHERE zone_id=?",
                     (int(overridden), now_iso(), zone_id))
        conn.execute(
            """INSERT INTO overrides (zone_id, overridden, updated_at) VALUES (?,?,?)
               ON CONFLICT(zone_id) DO UPDATE SET overridden=excluded.overridden,
               updated_at=excluded.updated_at""",
            (zone_id, int(overridden), now_iso()))


# ---- reports ----
def insert_report(conn: sqlite3.Connection, r: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO reports (report_id, zone_id, incident_type, latitude,
            longitude, description, timestamp, source, multiple_nearby, recent_timestamp,
            location_consistent, supporting_evidence, is_duplicate, human_verified,
            verified_by, verified_at, score, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (r.get("report_id"), r.get("zone_id"), r.get("incident_type"),
         r.get("latitude"), r.get("longitude"), r.get("description"),
         r.get("timestamp"), r.get("source", "crowdsourced"),
         int(bool(r.get("multiple_nearby"))), int(bool(r.get("recent_timestamp"))),
         int(bool(r.get("location_consistent"))), int(bool(r.get("supporting_evidence"))),
         int(bool(r.get("is_duplicate"))), int(bool(r.get("human_verified", False))),
         r.get("verified_by"), r.get("verified_at"),
         r.get("score", 0), r.get("status", "Low Confidence")),
    )


def get_reports() -> list[dict]:
    with get_conn() as conn:
        return [_row_to_dict(r) for r in
                conn.execute("SELECT * FROM reports ORDER BY report_id")]


def next_report_id() -> int:
    with get_conn() as conn:
        r = conn.execute("SELECT COALESCE(MAX(report_id), 999) AS m FROM reports").fetchone()
        return int(r["m"]) + 1


# ---- teams ----
def upsert_team(conn: sqlite3.Connection, t: dict) -> None:
    conn.execute(
        """INSERT INTO teams (team_id, name, status, capacity, current_lat, current_lon,
            assigned_zone, eta_min) VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(team_id) DO UPDATE SET name=excluded.name, status=excluded.status,
            capacity=excluded.capacity, current_lat=excluded.current_lat,
            current_lon=excluded.current_lon, assigned_zone=excluded.assigned_zone,
            eta_min=excluded.eta_min""",
        (t["team_id"], t.get("name"), t.get("status", "Available"),
         t.get("capacity", 4), t.get("current_lat"), t.get("current_lon"),
         t.get("assigned_zone"), t.get("eta_min", 15)),
    )


def get_teams() -> list[dict]:
    with get_conn() as conn:
        return [_row_to_dict(r) for r in conn.execute("SELECT * FROM teams ORDER BY team_id")]


def dispatch_team(team_id: int, zone_id: str) -> Optional[dict]:
    with _lock, get_conn() as conn:
        r = conn.execute("SELECT * FROM teams WHERE team_id=?", (team_id,)).fetchone()
        if not r or r["status"] != "Available":
            return None
        conn.execute("UPDATE teams SET status='Dispatched', assigned_zone=? WHERE team_id=?",
                     (zone_id, team_id))
        r2 = conn.execute("SELECT * FROM teams WHERE team_id=?", (team_id,)).fetchone()
        return _row_to_dict(r2)


# ---- audit ----
def add_audit(text: str) -> dict:
    entry = {"timestamp": now_iso(), "text": text}
    with _lock, get_conn() as conn:
        cur = conn.execute("INSERT INTO audit_logs (timestamp, text) VALUES (?,?)",
                           (entry["timestamp"], entry["text"]))
        entry["id"] = cur.lastrowid
    return entry


def get_audit(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        return [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))]


# ---- data sources ----
def upsert_source(conn: sqlite3.Connection, s: dict) -> None:
    conn.execute(
        """INSERT INTO data_sources (source_id, category, display_name, status, last_updated,
            last_checked, last_successful_update, acquisition_time, processing_time, detail)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET category=excluded.category,
            display_name=excluded.display_name, status=excluded.status,
            last_updated=excluded.last_updated, last_checked=excluded.last_checked,
            last_successful_update=excluded.last_successful_update,
            acquisition_time=excluded.acquisition_time,
            processing_time=excluded.processing_time, detail=excluded.detail""",
        (s["source_id"], s.get("category"), s.get("display_name"),
         s.get("status", "demo"), s.get("last_updated", now_iso()),
         s.get("last_checked"), s.get("last_successful_update"),
         s.get("acquisition_time"), s.get("processing_time"), s.get("detail", "")),
    )


def get_sources() -> list[dict]:
    with get_conn() as conn:
        return [_row_to_dict(r) for r in conn.execute("SELECT * FROM data_sources ORDER BY source_id")]


def seed_all(zones: list[dict], reports: list[dict], teams: list[dict],
             sources: list[dict], audit_text: str) -> None:
    with _lock, get_conn() as conn:
        for z in zones:
            upsert_zone(conn, z)
        for r in reports:
            insert_report(conn, r)
        for t in teams:
            upsert_team(conn, t)
        for s in sources:
            upsert_source(conn, s)
        conn.execute("DELETE FROM audit_logs")
        conn.execute("INSERT INTO audit_logs (timestamp, text) VALUES (?,?)", (now_iso(), audit_text))


# ---- satellite products / analysis ----
def upsert_product(conn: sqlite3.Connection, p: dict) -> None:
    import json as _json
    conn.execute(
        """INSERT INTO satellite_products (product_id, satellite, provider, collection,
            acquisition_time, cloud_cover, preview_href, preview_cached, bbox, searched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(product_id) DO UPDATE SET satellite=excluded.satellite,
            provider=excluded.provider, collection=excluded.collection,
            acquisition_time=excluded.acquisition_time, cloud_cover=excluded.cloud_cover,
            preview_href=excluded.preview_href, preview_cached=excluded.preview_cached,
            bbox=excluded.bbox, searched_at=excluded.searched_at""",
        (p.get("product_id"), p.get("satellite"), p.get("provider"),
         p.get("collection"), p.get("acquisition_time"), p.get("cloud_cover"),
         p.get("preview_href"), int(bool(p.get("preview_cached", False))),
         _json.dumps(p.get("bbox") or []), p.get("searched_at", now_iso())),
    )


def get_products(satellite: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if satellite:
            rows = conn.execute("SELECT * FROM satellite_products WHERE satellite=? "
                                "ORDER BY acquisition_time DESC", (satellite,))
        else:
            rows = conn.execute("SELECT * FROM satellite_products "
                                "ORDER BY acquisition_time DESC")
        return [_row_to_dict(r) for r in rows]


def record_analysis(conn: sqlite3.Connection, a: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO satellite_analysis (analysis_id, created_at, mode,
            s1_product, s1_pre_product, s2_product, zones_updated, detail)
           VALUES (?,?,?,?,?,?,?,?)""",
        (a.get("analysis_id"), a.get("created_at", now_iso()), a.get("mode", "live"),
         a.get("s1_product"), a.get("s1_pre_product"), a.get("s2_product"),
         a.get("zones_updated", 0), a.get("detail", "")),
    )


def get_analyses(limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        return [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM satellite_analysis ORDER BY created_at DESC LIMIT ?", (limit,))]


def upsert_zone_metrics(conn: sqlite3.Connection, m: dict) -> None:
    import json as _json
    conn.execute(
        """INSERT INTO zone_metrics (zone_id, flood_extent, flood_severity, change_score,
            satellite_confidence, evidence, analysis_id, updated_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(zone_id) DO UPDATE SET flood_extent=excluded.flood_extent,
            flood_severity=excluded.flood_severity, change_score=excluded.change_score,
            satellite_confidence=excluded.satellite_confidence,
            evidence=excluded.evidence, analysis_id=excluded.analysis_id,
            updated_at=excluded.updated_at""",
        (m.get("zone_id"), m.get("flood_extent", 0), m.get("flood_severity", 0),
         m.get("change_score", 0), m.get("satellite_confidence", 0),
         _json.dumps(m.get("evidence") or []), m.get("analysis_id"), now_iso()),
    )


def get_zone_metrics() -> dict[str, dict]:
    with get_conn() as conn:
        return {r["zone_id"]: _row_to_dict(r) for r in conn.execute("SELECT * FROM zone_metrics")}


# ---- app state (data version, scheduler bookkeeping) ----
def set_state(key: str, value: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute("INSERT INTO app_state (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_state(key: str, default: str = "") -> str:
    with get_conn() as conn:
        r = conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


# ---- human verification ----
def verify_report(report_id: int, verifier: str) -> Optional[dict]:
    with _lock, get_conn() as conn:
        r = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
        if not r:
            return None
        conn.execute("UPDATE reports SET human_verified=1, verified_by=?, verified_at=?, "
                     "status='Human Verified' WHERE report_id=?",
                     (verifier, now_iso(), report_id))
        r2 = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
        return _row_to_dict(r2)
