"""Central configuration. All values overridable via environment variables."""
import os
from pathlib import Path


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


APP_MODE = os.getenv("APP_MODE", "demo").lower()  # demo | live
EARTH_ENGINE_ENABLED = os.getenv("EARTH_ENGINE_ENABLED", "false").lower() == "true"
SATELLITE_PROVIDER = os.getenv("SATELLITE_PROVIDER", "sentinel")
OSM_ENABLED = os.getenv("OSM_ENABLED", "true").lower() == "true"
POPULATION_PROVIDER = os.getenv("POPULATION_PROVIDER", "worldpop")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./goldenhour.db")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

# --- Study area: Chennai, Tamil Nadu, India (configurable bbox) ---
STUDY_AREA = {
    "name": os.getenv("STUDY_AREA_NAME", "Chennai"),
    "country": "India",
    "latitude": _get_float("STUDY_AREA_LAT", 13.0475),
    "longitude": _get_float("STUDY_AREA_LON", 80.2013),
    # [min_lon, min_lat, max_lon, max_lat]
    "bbox": [
        _get_float("STUDY_AREA_MIN_LON", 80.05),
        _get_float("STUDY_AREA_MIN_LAT", 12.90),
        _get_float("STUDY_AREA_MAX_LON", 80.32),
        _get_float("STUDY_AREA_MAX_LAT", 13.25),
    ],
}

GRID_ROWS = _get_int("GRID_ROWS", 6)
GRID_COLS = _get_int("GRID_COLS", 6)

# --- Golden Hour Score weights (prototype decision-support score) ---
GHS_WEIGHTS = {
    "populationRisk": _get_float("GHS_W_POPULATION", 0.24),
    "urgency": _get_float("GHS_W_URGENCY", 0.23),
    "vulnerability": _get_float("GHS_W_VULNERABILITY", 0.18),
    "severity": _get_float("GHS_W_SEVERITY", 0.17),
    "confidence": _get_float("GHS_W_CONFIDENCE", 0.11),
    "accessibility": _get_float("GHS_W_ACCESSIBILITY", 0.07),
}

# --- Damage score weights (transparent prototype) ---
DAMAGE_WEIGHTS = {
    "flood_extent": 0.50,
    "change_detection": 0.25,
    "building_exposure": 0.15,
    "imagery_confidence": 0.10,
}

# Incident urgency profiles: base urgency + linear decay (or rise for flooding).
# Illustrative curves only — NOT medically validated.
INCIDENT_PROFILES = {
    "Trapped Under Rubble": {"baseUrgency": 92, "decayPerMin": 0.12, "rising": False},
    "Medical Emergency": {"baseUrgency": 80, "decayPerMin": 0.35, "rising": False},
    "Stranded on Rooftop": {"baseUrgency": 70, "decayPerMin": 0.20, "rising": False},
    "Flooding - Rising Water": {"baseUrgency": 55, "decayPerMin": 0.0, "rising": True},
    "Property Damage": {"baseUrgency": 35, "decayPerMin": 0.50, "rising": False},
}

PRIORITY_THRESHOLDS = {"Critical": 85, "High": 65, "Medium": 40}

# --- Algorithmic report-confidence thresholds (configurable) ---
# Base +8, then +23 per satisfied evidence flag (max 98). Labels estimate
# confidence only — "Human Verified" requires explicit human action.
CONF_THRESHOLD_HIGH = _get_float("CONF_THRESHOLD_HIGH", 85)
CONF_THRESHOLD_MODERATE = _get_float("CONF_THRESHOLD_MODERATE", 65)
CONF_THRESHOLD_MEDIUM = _get_float("CONF_THRESHOLD_MEDIUM", 45)

# --- Satellite ingestion ---
# Provider order tried for open search: planetary-computer STAC first
# (no key needed), then Copernicus Data Space OData catalogue.
STAC_API_URL = os.getenv("STAC_API_URL",
                         "https://planetarycomputer.microsoft.com/api/stac/v1")
COPERNICUS_ODATA_URL = os.getenv("COPERNICUS_ODATA_URL",
                                 "https://catalogue.dataspace.copernicus.eu/odata/v1")
S1_COLLECTION = os.getenv("S1_COLLECTION", "sentinel-1-rtc")
S2_COLLECTION = os.getenv("S2_COLLECTION", "sentinel-2-l2a")
SATELLITE_REFRESH_MINUTES = _get_int("SATELLITE_REFRESH_MINUTES", 60)
SATELLITE_SCHEDULER_ENABLED = os.getenv("SATELLITE_SCHEDULER_ENABLED", "true").lower() == "true"
# Data is "fresh" if the latest successful satellite analysis is newer than this.
FRESHNESS_MINUTES = _get_int("FRESHNESS_MINUTES", 180)

# --- Study-area presets (default: Chennai; activation reseeds + re-searches) ---
STUDY_AREA_PRESETS = {
    "Chennai": {"country": "India", "latitude": 13.0475, "longitude": 80.2013,
                "bbox": [80.05, 12.90, 80.32, 13.25]},
    "Mumbai": {"country": "India", "latitude": 19.0760, "longitude": 72.8777,
               "bbox": [72.75, 18.90, 73.00, 19.25]},
    "Bengaluru": {"country": "India", "latitude": 12.9716, "longitude": 77.5946,
                  "bbox": [77.45, 12.85, 77.75, 13.10]},
    "Hyderabad": {"country": "India", "latitude": 17.3850, "longitude": 78.4867,
                  "bbox": [78.30, 17.25, 78.65, 17.55]},
    "Delhi": {"country": "India", "latitude": 28.6139, "longitude": 77.2090,
              "bbox": [76.95, 28.45, 77.35, 28.85]},
    "Kolkata": {"country": "India", "latitude": 22.5726, "longitude": 88.3639,
                "bbox": [88.20, 22.45, 88.50, 22.70]},
}

DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
S1_RAW_DIR = RAW_DIR / "sentinel1"
S2_RAW_DIR = RAW_DIR / "sentinel2"
FLOOD_DIR = PROCESSED_DIR / "flood"
NDWI_DIR = PROCESSED_DIR / "ndwi"
for _d in (RAW_DIR, PROCESSED_DIR, S1_RAW_DIR, S2_RAW_DIR, FLOOD_DIR, NDWI_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def resolve_db_path(db_url: str = DATABASE_URL) -> Path:
    if db_url.startswith("sqlite:///"):
        p = db_url.replace("sqlite:///", "")
        path = Path(p)
        if not path.is_absolute():
            # relative to backend/ dir
            path = Path(__file__).resolve().parents[1] / p
        return path
    return Path("goldenhour.db")
