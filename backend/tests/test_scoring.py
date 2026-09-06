"""Unit tests: scoring engine edge cases."""
from backend.app.scoring import ghs as g


def test_ghs_zero_floor():
    total, breakdown, _ = g.compute_ghs(0, 0, 0, 5, 0, 0)
    assert 0 <= total <= 100
    assert total == sum(breakdown.values()) or abs(total - sum(breakdown.values())) <= 3


def test_ghs_max_ceiling():
    total, _, _ = g.compute_ghs(100, 100, 100, 100, 100, 100)
    assert total == 100


def test_ghs_known_value():
    total, breakdown, _ = g.compute_ghs(80, 80, 70, 75, 90, 60)
    assert total == 77
    assert breakdown["populationRisk"] == 19


def test_classify_boundaries():
    assert g.classify(85) == "Critical"
    assert g.classify(84.9) == "High"
    assert g.classify(65) == "High"
    assert g.classify(64.9) == "Medium"
    assert g.classify(40) == "Medium"
    assert g.classify(39.9) == "Low"
    assert g.classify(0) == "Low"
    assert g.classify(100) == "Critical"


def test_urgency_decay_and_rising():
    assert g.compute_urgency("Trapped Under Rubble", 0) == 92
    assert g.compute_urgency("Trapped Under Rubble", 60) < 92
    assert g.compute_urgency("Property Damage", 120) == 5  # floor
    rising_early = g.compute_urgency("Flooding - Rising Water", 30)
    rising_peak = g.compute_urgency("Flooding - Rising Water", 45)
    assert rising_peak >= rising_early > 55
    assert g.compute_urgency("Unknown Type", 0) == 50


def test_silent_zone():
    assert g.is_silent_zone(65, 2) is True
    assert g.is_silent_zone(90, 0) is True
    assert g.is_silent_zone(64.9, 0) is False
    assert g.is_silent_zone(90, 3) is False


def test_report_confidence_ladder():
    s, label = g.score_report(True, True, True, True)
    assert (s, label) == (98, "High Confidence")
    s, label = g.score_report(True, True, True, False)
    assert label == "Moderate Confidence"
    s, label = g.score_report(True, True, False, False)
    assert label == "Medium Confidence"
    s, label = g.score_report(False, False, False, False)
    assert label == "Low Confidence"
    s, label = g.score_report(True, True, True, True, is_duplicate=True)
    assert label == "Potential Duplicate"


def test_confidence_thresholds_configurable():
    s, label = g.score_report(True, True, True, False,
                              thresholds={"high": 70, "moderate": 60, "medium": 50})
    assert label == "High Confidence"  # 77 >= custom 70


def test_duplicate_detection():
    existing = [{"zone_id": "Z-001", "incident_type": "Medical Emergency",
                 "timestamp": "2026-09-06T12:00:00"}]
    assert g.detect_duplicate({"zone_id": "Z-001", "incident_type": "Medical Emergency",
                               "timestamp": "2026-09-06T12:10:00"}, existing) is True
    assert g.detect_duplicate({"zone_id": "Z-001", "incident_type": "Medical Emergency",
                               "timestamp": "2026-09-06T14:00:00"}, existing) is False
    assert g.detect_duplicate({"zone_id": "Z-002", "incident_type": "Medical Emergency",
                               "timestamp": "2026-09-06T12:05:00"}, existing) is False
