"""Flask app: JSON API under /api, plus the web page.  Run:  python -m backend.app"""
import csv
import hmac
import io
import os
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory


from backend import analytics, rag
from backend.checklist import rules as checklist_rules
from backend.db import get_connection, list_facilities
from backend.i18n import LANGUAGES, RTL, STRINGS
from backend.translation import LANGUAGE_NAMES, translate_explanation
from backend.first_aid import danger_signs, first_aid
from backend.understanding import understand, understand_audio
from backend.triage import CONDITIONS, DEFAULT_RADIUS_KM, INJURIES, rank_facilities

WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / "web"
LOCALITIES_FILE = Path(__file__).resolve().parent.parent / "data" / "localities.json"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.errorhandler(404)
def not_found(err):
    """A mistyped or old link opens the app, never an error page: people reach Raahat from shared links."""
    if request.path.startswith("/api/"):
        return {"error": "not found"}, 404
    return redirect("/", code=302)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/i18n")
def i18n():
    return jsonify({"languages": LANGUAGES, "rtl": sorted(RTL), "strings": STRINGS})


@app.get("/api/injuries")
def injuries():
    return jsonify([{"key": k, "label": v["label"], "group": v["group"],
                     "specialist_data": bool(v["primary"])} for k, v in INJURIES.items()])


@app.get("/api/conditions")
def conditions():
    return jsonify([{"key": k, "label": v["label"]} for k, v in CONDITIONS.items()])


@app.get("/api/sources")
def sources():
    return jsonify([{"doc_id": k, "title": v, "kind": "legal" if k in rag.LEGAL_DOCS else "first_aid",
                     "verified": rag.doc_verified(k)}
                    for k, v in rag.DOC_TITLES.items()])


@app.get("/api/first_aid")
def first_aid_card():
    """Fixed, sourced first-aid steps for an injury (translated if a language is given)."""
    injury = request.args.get("injury")
    language = request.args.get("language", "en")
    if injury not in INJURIES or language not in LANGUAGE_NAMES:
        return {"error": "injury and language must be valid keys"}, 400
    return jsonify(first_aid(injury, language))


@app.get("/api/danger_signs")
def danger_signs_card():
    """Fixed, sourced danger signs for a patient condition (pregnant, chemotherapy, ...)."""
    condition = request.args.get("condition")
    language = request.args.get("language", "en")
    if condition not in CONDITIONS or language not in LANGUAGE_NAMES:
        return {"error": "condition and language must be valid keys"}, 400
    return jsonify(danger_signs(condition, language))


def _conditions(body: dict) -> list[str] | None:
    conds = body.get("conditions") or []
    if not isinstance(conds, list) or any(c not in CONDITIONS for c in conds):
        return None
    return list(dict.fromkeys(conds))


@app.get("/api/situations")
def situations():
    return jsonify([{"key": k, "label": v["label"]} for k, v in rag.SITUATIONS.items()])


@app.get("/api/localities")
def localities():
    """Areas a person can pick as their starting point (OpenStreetMap coordinates), grouped by zone."""
    return send_from_directory(LOCALITIES_FILE.parent, LOCALITIES_FILE.name, mimetype="application/json")


@app.get("/api/helplines")
def helplines():
    """National and Hyderabad helplines (108, 112, Tele-MANAS, Roshni, Childline, Women Helpline), each sourced."""
    return send_from_directory(LOCALITIES_FILE.parent, "helplines.json", mimetype="application/json")


@app.get("/api/checklist")
def checklist():
    """Rules for the 'documents to carry' card; the page combines them with the person's choices."""
    return jsonify(checklist_rules())


def _session(body: dict) -> str | None:
    s = body.get("session")
    return s if isinstance(s, str) and s.isascii() and 0 < len(s) <= 40 else None


def _lang(body: dict) -> str | None:
    return body.get("language") if body.get("language") in LANGUAGE_NAMES else None


@app.post("/api/event")
def event():
    """Anonymous client events: a button pressed, 'was this helpful', a problem reported."""
    body = request.get_json(silent=True, force=True) or {}  # sendBeacon posts text/plain
    kind, value = body.get("kind"), body.get("value")
    allowed = {"action": analytics.ACTIONS, "feedback": ("yes", "no"), "report": analytics.REPORTS}
    if kind not in allowed or value not in allowed[kind]:
        return {"error": "unknown event"}, 400
    extra = {}
    if kind == "feedback":
        if body.get("target") not in analytics.FEEDBACK_TARGETS:
            return {"error": "unknown feedback target"}, 400
        extra["target"] = body["target"]
        if isinstance(body.get("doc_ids"), list):
            extra["doc_ids"] = [d for d in body["doc_ids"] if d in rag.DOC_TITLES]
    if body.get("tier") in ("specialist", "can_manage", "stabilize", "unsuitable"):
        extra["tier"] = body["tier"]
    fid = body.get("facility_id")
    injury = body.get("injury") if body.get("injury") in INJURIES else None
    analytics.log(kind, session=_session(body), language=_lang(body), injury=injury,
                  facility_id=fid if isinstance(fid, int) else None, value=value, extra=extra or None,
                  text=body.get("comment") if kind == "report" and isinstance(body.get("comment"), str) else None)
    return {"ok": True}


def _require_admin() -> None:
    token = os.getenv("ADMIN_TOKEN")
    given = request.headers.get("X-Admin-Token") or request.args.get("token") or ""
    if not token or not hmac.compare_digest(given, token):
        abort(404)  # don't reveal that the endpoint exists


@app.get("/api/admin/stats")
def admin_stats():
    _require_admin()
    return jsonify(analytics.summary())


@app.get("/api/admin/events.csv")
def admin_events_csv():
    _require_admin()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["id", *analytics.COLUMNS])
    writer.writeheader()
    writer.writerows(analytics.rows())
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=raahat-events.csv"})


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
    conds = _conditions(body)
    if conds is None:
        return {"error": f"conditions must be a list drawn from {list(CONDITIONS)}"}, 400

    with get_connection() as conn:
        ranked = rank_facilities(list_facilities(conn), injury, lat, lng, radius, tuple(conds))
    if _session(body):  # the page's own example preview sends no session and isn't counted
        area = body.get("area") if isinstance(body.get("area"), str) else None
        analytics.log("search", session=_session(body), language=_lang(body), injury=injury, conditions=conds,
                      area=(area[:40] if area else analytics.coarse_area(lat, lng)),
                      extra={"results": len(ranked), "top_tier": ranked[0]["tier"] if ranked else None,
                             "specialists": sum(r["tier"] == "specialist" for r in ranked), "radius_km": radius})
    return jsonify({"injury": {"key": injury, "label": INJURIES[injury]["label"],
                               "specialist_data": bool(INJURIES[injury]["primary"]),
                               # The specialist team it needs, matched against what the scheme lists a hospital
                               # for. Empty for emergencies handled by emergency medicine: schemes don't list that.
                               "needs": INJURIES[injury]["primary"]},
                    "conditions": conds,
                    "origin": {"lat": lat, "lng": lng},
                    "results": ranked})


@app.post("/api/understand")
def understand_text():
    """Free-text description -> suggested injury + situations, for the user to confirm."""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()[:1000]
    if not text:
        return {"error": "text is required"}, 400
    result = understand(text)
    analytics.log("understand", session=_session(body), language=_lang(body), text=text,
                  injury=(result or {}).get("injury"), conditions=(result or {}).get("conditions"),
                  extra={"understood": bool(result and result.get("injury")), "ai_available": result is not None,
                         "life_threatening": bool(result and result.get("life_threatening_signs"))})
    if result is None:
        return {"error": "The AI service is busy. Please choose from the list instead."}, 503
    return jsonify(result)


MAX_AUDIO_BYTES = 6 * 1024 * 1024  # ~3 minutes of 16 kHz mono WAV; the page stops at 90 s
AUDIO_TYPES = ("audio/wav", "audio/x-wav", "audio/mp3", "audio/mpeg", "audio/ogg", "audio/aac", "audio/flac", "audio/webm")


@app.post("/api/understand_audio")
def understand_spoken():
    """A spoken description (raw audio body) -> what was heard + the same fields as /api/understand.

    The recording is sent to Gemini and not stored; only the scrubbed transcript is logged, like typed text.
    """
    mime = (request.mimetype or "").lower()
    if mime not in AUDIO_TYPES:
        return {"error": f"Content-Type must be one of {list(AUDIO_TYPES)}"}, 415
    audio = request.get_data(cache=False)
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        return {"error": "audio is empty or too long"}, 413
    lang = request.args.get("language")
    result = understand_audio(audio, "audio/wav" if mime == "audio/x-wav" else mime,
                              LANGUAGE_NAMES.get(lang))
    session = request.args.get("session")
    analytics.log("understand", session=session if session and session.isascii() and len(session) <= 40 else None,
                  language=lang if lang in LANGUAGE_NAMES else None, text=(result or {}).get("transcript"),
                  injury=(result or {}).get("injury"), conditions=(result or {}).get("conditions"),
                  extra={"voice": True, "understood": bool(result and result.get("injury")),
                         "ai_available": result is not None, "area": bool(result and result.get("area")),
                         "life_threatening": bool(result and result.get("life_threatening_signs")),
                         "audio_kb": round(len(audio) / 1024), "model": (result or {}).get("model")})
    if result is None:
        return {"error": "The AI service is busy. Please type or choose from the list instead."}, 503
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
    question = (body.get("question") or "").strip()[:500] or None
    history = body.get("history") or []
    if not isinstance(history, list) or not all(
            isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
            for m in history):
        return {"error": "history must be a list of {role: user|assistant, content: str}"}, 400
    language = body.get("language") or "en"
    if language not in LANGUAGE_NAMES:
        return {"error": f"language must be one of {list(LANGUAGE_NAMES)}"}, 400
    conds = _conditions(body)
    if conds is None:
        return {"error": f"conditions must be a list drawn from {list(CONDITIONS)}"}, 400
    started = time.monotonic()
    try:
        result = rag.explain(INJURIES[injury]["label"], facility, situation, tags, question, history, injury, conds)
        # English stays authoritative; the translation is an extra, checked field.
        result["language"] = language
        result["explanation_translated"] = (
            translate_explanation(result["explanation"], language) if result["generated"] else None)
    except rag.AI_ERRORS:
        return {"error": "The AI service is busy. Please try again in a moment."}, 503
    analytics.log("answer", session=_session(body), language=language, injury=injury, conditions=conds,
                  situations=tags, facility_id=facility["id"] if facility else None, text=question,
                  extra={"overview": question is None, "low_confidence": result["low_confidence"],
                         "confidence": result["confidence"], "generated": result["generated"],
                         "sources": [s["doc_id"] for s in result["sources"]],
                         "seconds": round(time.monotonic() - started, 1)})
    return jsonify(result)


if __name__ == "__main__":
    # Reloader off by default: it restarts mid-request when OneDrive/Streamlit touch project files.
    app.run(port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
