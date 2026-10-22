"""Anonymous usage events and feedback, for validating Raahat with real use.

Stored: what kind of emergency, language, area (a named locality, or GPS rounded to
~1 km), which hospital tier was chosen, questions with numbers and emails removed,
and "was this helpful". Never stored: IP address, user agent, names typed into forms
on purpose, exact location. `session` is a random id the page makes per case, so
events from one case can be grouped without knowing who it was.

Storage: Postgres when DATABASE_URL is set (needed on Render, whose disk is wiped on
every restart), otherwise data/analytics.db. Every event is also printed to the log.
"""
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "analytics.db"
DATABASE_URL = os.getenv("DATABASE_URL", "")

KINDS = ("search", "understand", "answer", "feedback", "action", "report")
# Client-reported values, so the table stays a closed vocabulary rather than free text.
ACTIONS = ("call_108", "call_hospital", "call_helpline", "directions", "share", "read_aloud", "checklist_tick", "geo_used",
           "desk_card", "offline_search")
FEEDBACK_TARGETS = ("answer", "results", "first_aid", "checklist")
REPORTS = ("no_emergency", "wrong_phone", "no_aarogyasri", "closed", "other")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          {pk},
    ts          TEXT NOT NULL,          -- UTC, to the minute
    session     TEXT,
    kind        TEXT NOT NULL,
    language    TEXT,
    injury      TEXT,
    conditions  TEXT,                   -- JSON list
    situations  TEXT,                   -- JSON list
    area        TEXT,                   -- locality name or lat,lng rounded to 2 decimals
    facility_id INTEGER,
    value       TEXT,                   -- action / feedback / report value
    text        TEXT,                   -- scrubbed question or description
    extra       TEXT                    -- JSON: counts, tiers, confidence
)"""
COLUMNS = ("ts", "session", "kind", "language", "injury", "conditions", "situations", "area",
           "facility_id", "value", "text", "extra")

_lock = threading.Lock()
_ready = False

# Long digit runs (phone, Aadhaar, card numbers), emails.
_DIGITS_RX = re.compile(r"(?<!\w)\+?\d[\d\s-]{5,}\d(?!\w)")
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def scrub(text: str | None, limit: int = 300) -> str | None:
    if not text:
        return None
    text = _EMAIL_RX.sub("[email]", text)
    text = _DIGITS_RX.sub("[number]", text)
    return text.strip()[:limit] or None


def coarse_area(lat: float, lng: float) -> str:
    """~1 km: enough to see which parts of the city use Raahat, not who."""
    return f"{lat:.2f},{lng:.2f}"


def _connect():
    if DATABASE_URL:
        import psycopg  # only needed when Postgres is configured
        return psycopg.connect(DATABASE_URL, autocommit=True)
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(SQLITE_PATH)


def _sql(q: str) -> str:
    return q.replace("?", "%s") if DATABASE_URL else q


def _ensure(conn) -> None:
    global _ready
    if not _ready:
        pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        conn.execute(SCHEMA.format(pk=pk))
        if not DATABASE_URL:
            conn.commit()
        _ready = True


def log(kind: str, *, session: str | None = None, language: str | None = None, injury: str | None = None,
        conditions: list | None = None, situations: list | None = None, area: str | None = None,
        facility_id: int | None = None, value: str | None = None, text: str | None = None,
        extra: dict | None = None) -> None:
    """Record one event. Never raises: logging must not break an emergency lookup."""
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "session": (session or "")[:40] or None, "kind": kind, "language": language, "injury": injury,
        "conditions": json.dumps(conditions) if conditions else None,
        "situations": json.dumps(situations) if situations else None,
        "area": area, "facility_id": facility_id, "value": value, "text": scrub(text),
        "extra": json.dumps(extra) if extra else None,
    }
    print("RAAHAT_EVENT " + json.dumps(row, ensure_ascii=False), flush=True)
    try:
        with _lock:
            conn = _connect()
            try:
                _ensure(conn)
                conn.execute(_sql(f"INSERT INTO events ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})"),
                             [row[c] for c in COLUMNS])
                if not DATABASE_URL:
                    conn.commit()
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001 -- the printed line above is the fallback record
        print(f"RAAHAT_EVENT_STORE_FAILED {type(e).__name__}: {e}", flush=True)


def rows() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            _ensure(conn)
            cur = conn.execute(f"SELECT id, {', '.join(COLUMNS)} FROM events ORDER BY id")
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]
        finally:
            conn.close()


def summary() -> dict:
    """Headline numbers for a pitch slide: usage, actions taken, and how helpful people found it."""
    events = rows()
    by_kind: dict[str, int] = {}
    for e in events:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1

    def count(field: str, kind: str | None = None) -> dict:
        out: dict[str, int] = {}
        for e in events:
            if (kind is None or e["kind"] == kind) and e[field]:
                out[e[field]] = out.get(e[field], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    helpful: dict[str, dict[str, int]] = {}
    for e in events:
        if e["kind"] == "feedback" and e["value"] in ("yes", "no"):
            target = json.loads(e["extra"] or "{}").get("target", "answer")
            helpful.setdefault(target, {"yes": 0, "no": 0})[e["value"]] += 1
    answers = [json.loads(e["extra"] or "{}") for e in events if e["kind"] == "answer"]
    sessions = {e["session"] for e in events if e["session"]}
    searched = {e["session"] for e in events if e["kind"] == "search" and e["session"]}
    acted = {e["session"] for e in events if e["kind"] == "action" and e["session"]
             and e["value"] in ("call_108", "call_hospital", "directions", "share", "desk_card")}
    return {
        "events": len(events),
        "sessions": len(sessions),
        "first_event": events[0]["ts"] if events else None,
        "last_event": events[-1]["ts"] if events else None,
        "by_kind": by_kind,
        "searches_by_injury": count("injury", "search"),
        "by_language": count("language"),
        "actions": count("value", "action"),
        "sessions_that_searched": len(searched),
        "sessions_that_took_action": len(acted & searched),
        "helpful": helpful,
        "answers": {"total": len(answers),
                    "low_confidence": sum(1 for a in answers if a.get("low_confidence"))},
        "reports": count("value", "report"),
    }
