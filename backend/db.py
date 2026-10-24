"""SQLite access for the facility registry."""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "healthcare.db"

# Controlled vocabularies — the stage-2 injury matcher keys off these exact strings.
FACILITY_TYPES = ("govt", "charitable", "empanelled_private", "private", "unknown")

# How much Raahat has checked a hospital, strongest first (shown on every card).
DATA_LEVELS = ("phone_verified", "public", "registry", "unchecked")

SPECIALTIES = (
    "emergency_medicine",
    "general_medicine",
    "general_surgery",
    "orthopedics",
    "hand_surgery",
    "plastic_surgery",
    "neurosurgery",
    "burns",
    "cardiology",
    "pediatrics",
    "obstetrics",
    "ophthalmology",
    "oncology",
    "psychiatry",
)

# 0 = no emergency trauma care (refer out)
# 1 = basic: first aid, stabilization, suturing
# 2 = intermediate: fractures, minor/moderate surgery, 24x7 casualty
# 3 = advanced: major trauma centre (polytrauma, neuro, ICU, blood bank)
TRAUMA_LEVELS = {0: "none", 1: "basic", 2: "intermediate", 3: "advanced"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS facilities (
    id                     INTEGER PRIMARY KEY,
    name                   TEXT    NOT NULL,
    locality               TEXT    NOT NULL,
    district               TEXT    NOT NULL,
    lat                    REAL    NOT NULL,
    lng                    REAL    NOT NULL,
    type                   TEXT    NOT NULL CHECK (type IN ('govt','charitable','empanelled_private','private','unknown')),
    specialties            TEXT    NOT NULL,  -- JSON list drawn from SPECIALTIES
    trauma_level           INTEGER NOT NULL CHECK (trauma_level BETWEEN 0 AND 3),
    emergency_24x7         INTEGER CHECK (emergency_24x7 IN (0,1)),  -- NULL = not confirmed by a source
    aarogyasri_empanelled  INTEGER CHECK (aarogyasri_empanelled IN (0,1)),  -- NULL = not verified
    aarogyasri_evidence    TEXT    CHECK (aarogyasri_evidence IN ('official','reported')),
    sources                TEXT    NOT NULL DEFAULT '[]',  -- JSON list of {label, url}
    -- Specialities the scheme (Aarogyasri / PM-JAY) lists this hospital for, from SPECIALTIES.
    -- NULL = not verified; a list may be incomplete, so the app never says "not covered" from it.
    scheme_specialties     TEXT,
    scheme_source          TEXT,                            -- JSON {label, url} for that list
    pmjay_id               TEXT,                            -- registry ID, to look the hospital up by hand
    phone                  TEXT,                            -- JSON {number, kind: emergency|main|helpline|unverified, source}; NULL = none
    checked_on             TEXT,
    -- phone_verified: someone called and asked; public: researched from cited public sources;
    -- unchecked: only listed (OpenStreetMap), capabilities unknown -- "call first".
    data_level             TEXT    NOT NULL DEFAULT 'public' CHECK (data_level IN ('phone_verified','public','registry','unchecked')),
    is_synthetic           INTEGER NOT NULL DEFAULT 1
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS facilities")  # always rebuilt from the seed files
    conn.executescript(SCHEMA)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["specialties"] = json.loads(d["specialties"])
    d["sources"] = json.loads(d["sources"])
    for field in ("scheme_specialties", "scheme_source", "phone"):
        d[field] = json.loads(d[field]) if d[field] else None
    d["trauma_label"] = TRAUMA_LEVELS[d["trauma_level"]]
    d["is_synthetic"] = bool(d["is_synthetic"])
    # Tri-state: True / False / None (not verified)
    for flag in ("emergency_24x7", "aarogyasri_empanelled"):
        if d[flag] is not None:
            d[flag] = bool(d[flag])
    return d


def list_facilities(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM facilities ORDER BY id").fetchall()
    return [_row_to_dict(r) for r in rows]
