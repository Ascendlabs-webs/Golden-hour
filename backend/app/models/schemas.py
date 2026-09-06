"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ReportIn(BaseModel):
    zone_id: str
    incident_type: str = "Property Damage"
    latitude: float
    longitude: float
    description: str = ""
    source: str = "crowdsourced"


class DispatchIn(BaseModel):
    zone_id: Optional[str] = None  # None => auto top-priority unassigned


class OverrideIn(BaseModel):
    overridden: bool = True


class ZoneOut(BaseModel):
    zone_id: str
    neighbourhood: Optional[str] = None
    row: Optional[int] = None
    col: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    severity: float = 0
    population_risk: float = 0
    vulnerability: float = 0
    accessibility: float = 0
    confidence: float = 0
    reports_count: int = 0
    incident_type: Optional[str] = None
    flood_extent: float = 0
    estimated_population: int = 0
    manual_override: bool = False
    last_updated: Optional[str] = None
    golden_hour_score: int = 0
    breakdown: dict = Field(default_factory=dict)
    values: dict = Field(default_factory=dict)
    urgency: float = 0
    priority_class: str = "Low"
    silent_zone: bool = False


class HealthOut(BaseModel):
    status: str
    mode: str
    study_area: str
    zones: int
    reports: int
    teams: int
