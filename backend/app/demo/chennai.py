"""Deterministic Chennai flood-scenario demo data.

No Math.random() / random module here: every value derives from a stable
hash of its seed string, so the demo is reproducible on every machine.
Realistic Chennai geography (neighbourhood names + approximate centroids);
incident values are synthetic but fixed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

STUDY_BBOX = [80.05, 12.90, 80.32, 13.25]  # min_lon, min_lat, max_lon, max_lat

# 36 Chennai neighbourhoods (row-major, 6x6 grid) with approx centroids.
NEIGHBOURHOODS = [
    # row 0 (north)
    ("Ennore", 13.2210, 80.3150), ("Manali", 13.1930, 80.2700),
    ("Madhavaram", 13.1700, 80.2400), ("Kolathur", 13.1450, 80.2150),
    ("Perambur", 13.1250, 80.2350), ("Tondiarpet", 13.1250, 80.2850),
    # row 1
    ("Korukkupet", 13.1100, 80.2850), ("Royapuram", 13.1000, 80.2900),
    ("Ayanavaram", 13.1000, 80.2300), ("Kilpauk", 13.0850, 80.2250),
    ("Egmore", 13.0770, 80.2600), ("Chepauk", 13.0650, 80.2800),
    # row 2
    ("Chetpet", 13.0750, 80.2400), ("Nungambakkam", 13.0600, 80.2400),
    ("T. Nagar", 13.0400, 80.2350), ("Saidapet", 13.0250, 80.2250),
    ("Mylapore", 13.0350, 80.2700), ("Triplicane", 13.0550, 80.2750),
    # row 3
    ("Kotturpuram", 13.0150, 80.2450), ("Adyar", 13.0050, 80.2600),
    ("Guindy", 13.0100, 80.2150), ("Velachery", 12.9750, 80.2200),
    ("Perungudi", 12.9650, 80.2450), ("Tharamani", 12.9800, 80.2500),
    # row 4
    ("St. Thomas Mount", 12.9950, 80.1950), ("Pallavaram", 12.9650, 80.1850),
    ("Medavakkam", 12.9550, 80.2050), ("Pallikaranai", 12.9450, 80.2150),
    ("Sholinganallur", 12.9350, 80.2350), ("Karapakkam", 12.9500, 80.2500),
    # row 5 (south)
    ("Tambaram", 12.9250, 80.1650), ("Chromepet", 12.9450, 80.1750),
    ("Selaiyur", 12.9350, 80.1850), ("Kovilambakkam", 12.9450, 80.1950),
    ("Nanmangalam", 12.9350, 80.1750), ("Medavakkam South", 12.9150, 80.2050),
]

INCIDENT_CYCLE = [
    "Flooding - Rising Water",
    "Stranded on Rooftop",
    "Medical Emergency",
    "Trapped Under Rubble",
    "Property Damage",
    "Flooding - Rising Water",
]

TEAM_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
              "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima"]

BASE_TIME = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def _h(seed: str) -> int:
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)


def _range(seed: str, lo: int, hi: int) -> int:
    return lo + _h(seed) % (hi - lo + 1)


def zone_id(i: int) -> str:
    return f"Z-{i + 1:03d}"


def generate_demo_zones(rows: int = 6, cols: int = 6) -> list[dict]:
    zones = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            name, lat, lon = NEIGHBOURHOODS[idx % len(NEIGHBOURHOODS)]
            profile = INCIDENT_CYCLE[idx % len(INCIDENT_CYCLE)]
            # Flood-prone low-lying belt (Adyar river / Velachery / Pallikaranai
            # marsh / Buckingham canal) gets higher severity deterministically.
            flood_prone = name in {"Adyar", "Velachery", "Perungudi", "Pallikaranai",
                                   "Kotturpuram", "Saidapet", "Tharamani", "Mylapore",
                                   "Sholinganallur", "Medavakkam", "Guindy"}
            sev_lo, sev_hi = (62, 96) if flood_prone else (28, 74)
            pop_lo, pop_hi = (55, 96) if idx % 3 != 2 else (20, 60)
            zones.append({
                "zone_id": zone_id(idx),
                "neighbourhood": name,
                "row": r, "col": c,
                "latitude": lat, "longitude": lon,
                "severity": _range(f"sev-{idx}", sev_lo, sev_hi),
                "population_risk": _range(f"pop-{idx}", pop_lo, pop_hi),
                "vulnerability": _range(f"vul-{idx}", 25, 92),
                "accessibility": _range(f"acc-{idx}", 28, 95),
                "confidence": _range(f"con-{idx}", 42, 96),
                "reports_count": _range(f"rep-{idx}", 0, 11),
                "incident_type": profile,
                "flood_extent": round((_range(f"fld-{idx}", 5, 95) / 100), 3),
                "estimated_population": _range(f"exppop-{idx}", 800, 24000),
            })
            idx += 1
    # Force two silent zones (high pop, few reports) for the demo narrative.
    for z in zones:
        if z["neighbourhood"] == "Pallikaranai":
            z["population_risk"] = 88
            z["reports_count"] = 1
        if z["neighbourhood"] == "Sholinganallur":
            z["population_risk"] = 81
            z["reports_count"] = 2
    return zones


def generate_demo_reports(zones: list[dict], count: int = 40) -> list[dict]:
    reports = []
    for i in range(count):
        z = zones[_h(f"rz-{i}") % len(zones)]
        age_min = 1 + _h(f"age-{i}") % 90
        multiple = _h(f"m-{i}") % 100 > 35
        recent = age_min < 30
        loc_ok = _h(f"l-{i}") % 100 > 25
        evid = _h(f"e-{i}") % 100 > 40
        dup = _h(f"d-{i}") % 100 < 12
        score = 8 + (23 if multiple else 0) + (23 if recent else 0) \
            + (23 if loc_ok else 0) + (23 if evid else 0)
        score = max(0, min(98, score))
        if dup:
            status = "Potential Duplicate"
        elif score >= 85:
            status = "High Confidence"
        elif score >= 65:
            status = "Moderate Confidence"
        elif score >= 45:
            status = "Medium Confidence"
        else:
            status = "Low Confidence"
        ts = (BASE_TIME - timedelta(minutes=age_min)).isoformat()
        # deterministic jitter around zone centroid
        jlat = ((_h(f"jlat-{i}") % 200) - 100) / 10000.0
        jlon = ((_h(f"jlon-{i}") % 200) - 100) / 10000.0
        reports.append({
            "report_id": 1000 + i,
            "zone_id": z["zone_id"],
            "incident_type": z["incident_type"],
            "latitude": round(z["latitude"] + jlat, 5),
            "longitude": round(z["longitude"] + jlon, 5),
            "description": f"Crowdsourced report near {z['neighbourhood']}: {z['incident_type'].lower()} reported by residents.",
            "timestamp": ts,
            "age_min": age_min,
            "source": "crowdsourced-demo",
            "multiple_nearby": multiple,
            "recent_timestamp": recent,
            "location_consistent": loc_ok,
            "supporting_evidence": evid,
            "is_duplicate": dup,
            "score": score,
            "status": status,
        })
    return reports


def generate_demo_teams() -> list[dict]:
    teams = []
    for i, name in enumerate(TEAM_NAMES):
        h = _h(f"team-{name}")
        teams.append({
            "team_id": i + 1,
            "name": f"Team {name}",
            "status": "Available" if h % 100 > 35 else "Dispatched",
            "capacity": 2 + h % 5,
            "current_lat": round(13.06 - (h % 40) / 1000.0, 5),
            "current_lon": round(80.20 + (h % 40) / 1000.0, 5),
            "assigned_zone": None,
            "eta_min": 6 + h % 30,
        })
    # First dispatched team gets a deterministic assignment for narrative.
    n = 0
    for t in teams:
        if t["status"] == "Dispatched" and n == 0:
            t["assigned_zone"] = "Z-020"
            n += 1
    return teams
