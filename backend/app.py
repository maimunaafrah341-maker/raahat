"""Flask API.  Run:  python -m backend.app"""
import os

from flask import Flask, jsonify, request

from google.genai import errors as genai_errors

from backend import rag
from backend.db import get_connection, list_facilities
from backend.triage import DEFAULT_RADIUS_KM, INJURIES, rank_facilities

app = Flask(__name__)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/injuries")
def injuries():
    return jsonify([{"key": k, "label": v["label"]} for k, v in INJURIES.items()])


@app.get("/api/facilities")
def facilities():
    with get_connection() as conn:
        return jsonify(list_facilities(conn))


@app.post("/api/triage")
def triage():
    body = request.get_json(silent=True) or {}
    injury = body.get("injury")
    if injury not in INJURIES:
        return {"error": f"injury must be one of {list(INJURIES)}"}, 400
    try:
        lat, lng = float(body["lat"]), float(body["lng"])
        radius = float(body.get("radius_km", DEFAULT_RADIUS_KM))
    except (KeyError, TypeError, ValueError):
        return {"error": "lat and lng are required numbers"}, 400

    with get_connection() as conn:
        ranked = rank_facilities(list_facilities(conn), injury, lat, lng, radius)
    return jsonify({"injury": {"key": injury, "label": INJURIES[injury]["label"]},
                    "origin": {"lat": lat, "lng": lng},
                    "results": ranked})


@app.post("/api/entitlements")
def entitlements():
    """Plain-language 'what you may be eligible for', grounded in the corpus via RAG."""
    body = request.get_json(silent=True) or {}
    injury = body.get("injury")
    if injury not in INJURIES:
        return {"error": f"injury must be one of {list(INJURIES)}"}, 400
    facility = None
    if body.get("facility_id") is not None:
        with get_connection() as conn:
            facility = next((f for f in list_facilities(conn) if f["id"] == body["facility_id"]), None)
        if facility is None:
            return {"error": "unknown facility_id"}, 404
    situation = (body.get("situation") or "").strip()[:500] or None
    try:
        return jsonify(rag.explain(INJURIES[injury]["label"], facility, situation))
    except genai_errors.APIError:
        return {"error": "The AI service is busy. Please try again in a moment."}, 503


if __name__ == "__main__":
    # Reloader off by default: it restarts mid-request when OneDrive/Streamlit touch project files.
    app.run(port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
