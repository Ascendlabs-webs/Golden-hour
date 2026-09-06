"""Reproducible Chennai demo: rebuild deterministic scenario into SQLite."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import database as db
from backend.app.processing import pipeline as pipe

if __name__ == "__main__":
    db.init_db()
    summary = pipe.refresh_demo()
    print(f"Demo loaded: {summary}")
    print("Start backend: py -m uvicorn backend.app.main:app --reload --port 8000")
