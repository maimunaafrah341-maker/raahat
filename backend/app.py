"""Flask API.  Run:  python -m backend.app"""
from flask import Flask, jsonify, request

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


if __name__ == "__main__":
    app.run(port=5000, debug=True)
