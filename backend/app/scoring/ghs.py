"""Golden Hour Score engine (pure functions — fully unit-tested)."""
from __future__ import annotations

from typing import Dict, Tuple

WEIGHTS = {
    "populationRisk": 0.24,
    "urgency": 0.23,
    "vulnerability": 0.18,
    "severity": 0.17,
    "confidence": 0.11,
    "accessibility": 0.07,
}

INCIDENT_PROFILES = {
    "Trapped Under Rubble": {"baseUrgency": 92, "decayPerMin": 0.12, "rising": False},
    "Medical Emergency": {"baseUrgency": 80, "decayPerMin": 0.35, "rising": False},
    "Stranded on Rooftop": {"baseUrgency": 70, "decayPerMin": 0.20, "rising": False},
    "Flooding - Rising Water": {"baseUrgency": 55, "decayPerMin": 0.0, "rising": True},
    "Property Damage": {"baseUrgency": 35, "decayPerMin": 0.50, "rising": False},
}


def clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def get_weights(overrides: Dict[str, float] | None = None) -> Dict[str, float]:
    w = dict(WEIGHTS)
    if overrides:
        for k, v in overrides.items():
            if k in w:
                w[k] = float(v)
    return w


def compute_urgency(incident_type: str, t_min: float = 0,
                    profiles: Dict | None = None) -> float:
    profiles = profiles or INCIDENT_PROFILES
    p = profiles.get(incident_type, {"baseUrgency": 50, "decayPerMin": 0.2, "rising": False})
    base = float(p.get("baseUrgency", 50))
    if p.get("rising"):
        if t_min <= 45:
            return clamp(base + 0.45 * t_min)
        return clamp(base + 0.45 * 45 - 0.6 * (t_min - 45))
    return clamp(base - float(p.get("decayPerMin", 0.2)) * t_min, 5, 100)


def compute_ghs(severity: float, population_risk: float, vulnerability: float,
                urgency: float, confidence: float, accessibility: float,
                weights: Dict[str, float] | None = None) -> Tuple[int, Dict[str, int], Dict[str, float]]:
    """Return (total, breakdown_contributions, values)."""
    w = get_weights(weights)
    values = {
        "severity": float(severity),
        "populationRisk": float(population_risk),
        "vulnerability": float(vulnerability),
        "urgency": float(urgency),
        "confidence": float(confidence),
        "accessibility": float(accessibility),
    }
    breakdown: Dict[str, int] = {}
    total = 0.0
    for key, weight in w.items():
        contrib = values[key] * weight
        breakdown[key] = round(contrib)
        total += contrib
    return round(clamp(total)), breakdown, values


def classify(total: float, thresholds: Dict[str, float] | None = None) -> str:
    th = thresholds or {"Critical": 85, "High": 65, "Medium": 40}
    if total >= th["Critical"]:
        return "Critical"
    if total >= th["High"]:
        return "High"
    if total >= th["Medium"]:
        return "Medium"
    return "Low"


def is_silent_zone(population_risk: float, reports_count: int,
                   pop_threshold: float = 65, report_threshold: int = 2) -> bool:
    return population_risk >= pop_threshold and reports_count <= report_threshold


def score_report(multiple_nearby: bool, recent: bool, location_consistent: bool,
                 supporting_evidence: bool, is_duplicate: bool = False,
                 thresholds: Dict[str, float] | None = None) -> Tuple[int, str]:
    """Transparent *algorithmic* confidence score 0-100 + label.

    The algorithm only estimates confidence from evidence flags — it does
    NOT fact-check. Only an explicit human action may label a report
    "Human Verified". Thresholds are configurable.
    """
    th = thresholds or {"high": 85, "moderate": 65, "medium": 45}
    score = 8
    if multiple_nearby:
        score += 23
    if recent:
        score += 23
    if location_consistent:
        score += 23
    if supporting_evidence:
        score += 23
    score = round(clamp(score, 0, 98))
    if is_duplicate:
        return score, "Potential Duplicate"
    if score >= th["high"]:
        return score, "High Confidence"
    if score >= th["moderate"]:
        return score, "Moderate Confidence"
    if score >= th["medium"]:
        return score, "Medium Confidence"
    return score, "Low Confidence"


def detect_duplicate(new_report: Dict, existing: list[Dict]) -> bool:
    """Heuristic: same zone + same incident type within 15 min -> potential duplicate."""
    for r in existing:
        if (r.get("zone_id") == new_report.get("zone_id")
                and r.get("incident_type") == new_report.get("incident_type")):
            try:
                import datetime as _dt
                fmt = "%Y-%m-%dT%H:%M:%S"
                a = _dt.datetime.fromisoformat(str(new_report.get("timestamp", ""))[:19])
                b = _dt.datetime.fromisoformat(str(r.get("timestamp", ""))[:19])
                if abs((a - b).total_seconds()) <= 15 * 60:
                    return True
            except Exception:
                # missing/invalid timestamps: fall back to exact zone+type match count
                return True
    return False
