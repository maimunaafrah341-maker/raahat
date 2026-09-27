"""SQLite access for the facility registry."""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "healthcare.db"

# Controlled vocabularies — the stage-2 injury matcher keys off these exact strings.
FACILITY_TYPES = ("govt", "charitable", "empanelled_private", "private")

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
    type                   TEXT    NOT NULL CHECK (type IN ('govt','charitable','empanelled_private','private')),
    specialties            TEXT    NOT NULL,  -- JSON list drawn from SPECIALTIES
    trauma_level           INTEGER NOT NULL CHECK (trauma_level BETWEEN 0 AND 3),
    emergency_24x7         INTEGER NOT NULL CHECK (emergency_24x7 IN (0,1)),
    aarogyasri_empanelled  INTEGER CHECK (aarogyasri_empanelled IN (0,1)),  -- NULL = not verified
    aarogyasri_evidence    TEXT    CHECK (aarogyasri_evidence IN ('official','reported')),
    sources                TEXT    NOT NULL DEFAULT '[]',  -- JSON list of {label, url}
    checked_on             TEXT,
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
    d["trauma_label"] = TRAUMA_LEVELS[d["trauma_level"]]
    for flag in ("emergency_24x7", "is_synthetic"):
        d[flag] = bool(d[flag])
    # Tri-state: True / False / None (not verified)
    if d["aarogyasri_empanelled"] is not None:
        d["aarogyasri_empanelled"] = bool(d["aarogyasri_empanelled"])
    return d


def list_facilities(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM facilities ORDER BY id").fetchall()
    return [_row_to_dict(r) for r in rows]
