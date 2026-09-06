"""Attempt a live refresh (OSM + Copernicus where configured)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import database as db
from backend.app.processing import pipeline as pipe

if __name__ == "__main__":
    db.init_db()
    summary = pipe.refresh_live()
    print(f"Live refresh attempted: {summary}")
