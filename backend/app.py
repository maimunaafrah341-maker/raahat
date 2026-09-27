"""Flask app: JSON API under /api, plus the web page.  Run:  python -m backend.app"""
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from google.genai import errors as genai_errors

from backend import rag
from backend.db import get_connection, list_facilities
from backend.i18n import LANGUAGES, RTL, STRINGS
from backend.translation import LANGUAGE_NAMES, translate_explanation
from backend.understanding import understand
from backend.triage import DEFAULT_RADIUS_KM, INJURIES, rank_facilities

WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/i18n")
def i18n():
    return jsonify({"languages": LANGUAGES, "rtl": sorted(RTL), "strings": STRINGS})


@app.get("/api/injuries")
def injuries():
    return jsonify([{"key": k, "label": v["label"]} for k, v in INJURIES.items()])


@app.get("/api/sources")
def sources():
    return jsonify([{"doc_id": k, "title": v} for k, v in rag.DOC_TITLES.items()])


@app.get("/api/situations")
def situations():
    return jsonify([{"key": k, "label": v["label"]} for k, v in rag.SITUATIONS.items()])


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


@app.post("/api/understand")
def understand_text():
    """Free-text description -> suggested injury + situations, for the user to confirm."""
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()[:1000]
    if not text:
        return {"error": "text is required"}, 400
    result = understand(text)
    if result is None:
        return {"error": "The AI service is busy. Please choose from the list instead."}, 503
    return jsonify(result)


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
    tags = body.get("situations") or []
    if not isinstance(tags, list) or any(t not in rag.SITUATIONS for t in tags):
        return {"error": f"situations must be a list drawn from {list(rag.SITUATIONS)}"}, 400
    language = body.get("language") or "en"
    if language not in LANGUAGE_NAMES:
        return {"error": f"language must be one of {list(LANGUAGE_NAMES)}"}, 400
    try:
        result = rag.explain(INJURIES[injury]["label"], facility, situation, tags)
        # English stays authoritative; the translation is an extra, checked field.
        result["language"] = language
        result["explanation_translated"] = (
            translate_explanation(result["explanation"], language) if result["generated"] else None)
        return jsonify(result)
    except genai_errors.APIError:
        return {"error": "The AI service is busy. Please try again in a moment."}, 503


if __name__ == "__main__":
    # Reloader off by default: it restarts mid-request when OneDrive/Streamlit touch project files.
    app.run(port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
