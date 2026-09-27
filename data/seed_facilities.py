"""Seed the facility registry.

Default: REAL Hyderabad hospitals from data/hospitals_real.json, where every
capability comes from a cited public source (see that file's "method").
--demo:  the original 18 SYNTHETIC facilities (fictional names, real localities).

Run:  python data/seed_facilities.py [--demo]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.db import (  # noqa: E402
    DB_PATH, FACILITY_TYPES, SPECIALTIES, get_connection, init_db, list_facilities,
)

REAL_FILE = Path(__file__).resolve().parent / "hospitals_real.json"

DISTRICT = "Hyderabad"

# (name, locality, lat, lng, type, specialties, trauma_level, emergency_24x7, aarogyasri_empanelled)
FACILITIES = [
    # --- Government ---
    ("Afzalgunj Government General Hospital", "Afzalgunj", 17.3713, 78.4804, "govt",
     ["emergency_medicine", "general_medicine", "general_surgery", "orthopedics",
      "plastic_surgery", "neurosurgery", "burns", "cardiology"], 3, True, True),
    ("Padmarao Nagar Government Teaching Hospital", "Padmarao Nagar", 17.4270, 78.5030, "govt",
     ["emergency_medicine", "general_surgery", "orthopedics", "hand_surgery",
      "plastic_surgery", "neurosurgery", "pediatrics", "obstetrics"], 3, True, True),
    ("Punjagutta State Institute of Medical Sciences", "Punjagutta", 17.4230, 78.4500, "govt",
     ["emergency_medicine", "general_surgery", "orthopedics", "plastic_surgery",
      "neurosurgery", "cardiology"], 3, True, True),
    ("Nampally Area Hospital", "Nampally", 17.3900, 78.4700, "govt",
     ["emergency_medicine", "general_medicine", "general_surgery", "orthopedics",
      "obstetrics"], 2, True, True),
    ("Malakpet Area Hospital", "Malakpet", 17.3760, 78.5010, "govt",
     ["emergency_medicine", "general_medicine", "general_surgery", "orthopedics",
      "pediatrics"], 2, True, True),
    ("Golconda Urban Primary Health Centre", "Golconda", 17.3850, 78.4040, "govt",
     ["general_medicine", "pediatrics"], 1, False, False),

    # --- Charitable ---
    ("Mehdipatnam Mission Hospital", "Mehdipatnam", 17.3960, 78.4380, "charitable",
     ["emergency_medicine", "general_surgery", "orthopedics", "general_medicine"], 2, True, True),
    ("Chandrayangutta Seva Trust Hospital", "Chandrayangutta", 17.3210, 78.4820, "charitable",
     ["emergency_medicine", "general_medicine", "general_surgery", "obstetrics"], 1, True, True),
    ("Amberpet Charitable Eye & General Hospital", "Amberpet", 17.3930, 78.5180, "charitable",
     ["ophthalmology", "general_medicine"], 0, False, True),

    # --- Aarogyasri-empanelled private ---
    ("Himayatnagar Hand & Microsurgery Centre", "Himayatnagar", 17.4010, 78.4870, "empanelled_private",
     ["emergency_medicine", "orthopedics", "hand_surgery", "plastic_surgery"], 2, True, True),
    ("Banjara Hills Multispeciality Hospital", "Banjara Hills", 17.4150, 78.4350, "empanelled_private",
     ["emergency_medicine", "general_surgery", "orthopedics", "hand_surgery", "plastic_surgery",
      "neurosurgery", "cardiology", "burns"], 3, True, True),
    ("Santoshnagar Care Hospital", "Santoshnagar", 17.3480, 78.5140, "empanelled_private",
     ["emergency_medicine", "general_medicine", "general_surgery", "orthopedics"], 2, True, True),
    ("Tolichowki Life Hospital", "Tolichowki", 17.3990, 78.4150, "empanelled_private",
     ["emergency_medicine", "general_surgery", "orthopedics", "pediatrics"], 2, True, True),
    ("Musheerabad Burns & Plastic Surgery Hospital", "Musheerabad", 17.4180, 78.5000, "empanelled_private",
     ["emergency_medicine", "burns", "plastic_surgery", "general_surgery"], 2, True, True),

    # --- Private, not empanelled ---
    ("Begumpet Premier Hospital", "Begumpet", 17.4440, 78.4630, "private",
     ["emergency_medicine", "general_surgery", "orthopedics", "hand_surgery", "plastic_surgery",
      "neurosurgery", "cardiology"], 3, True, False),
    ("Khairatabad Ortho Clinic", "Khairatabad", 17.4120, 78.4610, "private",
     ["orthopedics"], 1, False, False),
    ("Marredpally Heart Institute", "Marredpally", 17.4460, 78.5100, "private",
     ["emergency_medicine", "general_medicine", "cardiology"], 1, True, False),
    ("Asif Nagar Nursing Home", "Asif Nagar", 17.3870, 78.4520, "private",
     ["general_medicine", "general_surgery", "obstetrics"], 1, False, False),
]


def validate(rows) -> None:
    for name, _, lat, lng, ftype, specs, level, *_ in rows:
        assert ftype in FACILITY_TYPES, f"{name}: bad type {ftype}"
        bad = set(specs) - set(SPECIALTIES)
        assert not bad, f"{name}: unknown specialties {bad}"
        assert 0 <= level <= 3, f"{name}: bad trauma level"
        assert 17.2 < lat < 17.6 and 78.3 < lng < 78.6, f"{name}: outside Hyderabad"
    for r in rows:
        if r[4] == "empanelled_private":
            assert r[8], f"{r[0]}: empanelled_private must be Aarogyasri-empanelled"
        if r[4] == "private":
            assert not r[8], f"{r[0]}: private type must not be empanelled"


def validate_real(data: dict) -> None:
    for h in data["hospitals"]:
        name = h["name"]
        assert h["type"] in FACILITY_TYPES, f"{name}: bad type"
        assert not set(h["specialties"]) - set(SPECIALTIES), f"{name}: unknown specialty"
        assert 0 <= h["trauma_level"] <= 3, f"{name}: bad trauma level"
        assert 17.2 < h["lat"] < 17.6 and 78.3 < h["lng"] < 78.6, f"{name}: outside Hyderabad"
        assert h["sources"], f"{name}: every real hospital needs at least one source"
        emp, ev = h["aarogyasri_empanelled"], h["aarogyasri_evidence"]
        assert (emp is None) == (ev is None), f"{name}: empanelment status and evidence must go together"
        if h["type"] == "empanelled_private":
            assert emp and ev == "official", f"{name}: empanelled_private needs official evidence"


def seed(demo: bool = False) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if demo:
        validate(FACILITIES)
        rows = [(n, loc, lat, lng, t, json.dumps(s), lvl, int(er), int(ars), None, "[]", None, 1)
                for n, loc, lat, lng, t, s, lvl, er, ars in FACILITIES]
    else:
        data = json.loads(REAL_FILE.read_text(encoding="utf-8"))
        validate_real(data)
        rows = [(h["name"], h["locality"], h["lat"], h["lng"], h["type"], json.dumps(h["specialties"]),
                 h["trauma_level"], int(h["emergency_24x7"]),
                 None if h["aarogyasri_empanelled"] is None else int(h["aarogyasri_empanelled"]),
                 h["aarogyasri_evidence"], json.dumps(h["sources"]), data["checked_on"], 0)
                for h in data["hospitals"]]
    with get_connection() as conn:
        init_db(conn)
        conn.executemany(
            """INSERT INTO facilities
               (name, locality, district, lat, lng, type, specialties, trauma_level, emergency_24x7,
                aarogyasri_empanelled, aarogyasri_evidence, sources, checked_on, is_synthetic)
               VALUES (?, ?, 'Hyderabad', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        count = len(list_facilities(conn))
    print(f"Seeded {count} {'SYNTHETIC demo' if demo else 'real'} facilities into {DB_PATH}")


if __name__ == "__main__":
    seed(demo="--demo" in sys.argv)
