"""Expose scoring helpers at package level."""
from .ghs import (  # noqa: F401
    clamp,
    compute_ghs,
    compute_urgency,
    classify,
    is_silent_zone,
    score_report,
    detect_duplicate,
    get_weights,
    WEIGHTS,
    INCIDENT_PROFILES,
)
