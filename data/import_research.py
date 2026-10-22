"""Add or update researched hospitals from a spreadsheet (CSV) into data/hospitals_real.json.

Fill data/research_template.csv (Excel or Google Sheets: File > Download > CSV), then:

    python data/import_research.py data/my_research.csv
    python data/seed_facilities.py          # reload the database

A row whose name matches an existing hospital updates it; otherwise it is added. If lat/lng are
blank, the location is taken from the OpenStreetMap list (data/hospitals_osm.json) when the name
matches. Bad rows are reported and skipped; nothing is written unless the whole file stays valid.
See "Researching hospitals yourself" in the README for what counts as evidence.
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.db import SPECIALTIES  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from seed_facilities import REAL_FILE, OSM_FILE, validate_real  # noqa: E402

TYPES = ("govt", "charitable", "empanelled_private", "private")
YES_NO = {"yes": True, "no": False, "unknown": None, "": None}


def norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("hospitals", "hospital"))


def osm_lookup() -> dict:
    if not OSM_FILE.exists():
        return {}
    return {norm(h["name"]): h for h in json.loads(OSM_FILE.read_text(encoding="utf-8"))["hospitals"]}


def parse_row(row: dict, osm: dict) -> dict:
    """One spreadsheet row -> a hospitals_real.json entry. Raises ValueError with a plain-English reason."""
    get = lambda k: (row.get(k) or "").strip()  # noqa: E731
    name = get("name")
    if not name or "delete this row" in name.lower():
        raise ValueError("no name (or it is the example row)")
    sources = []
    for part in filter(None, (p.strip() for p in get("sources").split(";"))):
        label, _, url = part.rpartition("|")
        if not url.startswith("http"):
            raise ValueError(f"source '{part}' must be written as label|https://link")
        sources.append({"label": label.strip() or url, "url": url})
    lat, lng = get("lat"), get("lng")
    if not (lat and lng):
        match = osm.get(norm(name))
        if not match:
            raise ValueError("lat/lng are blank and the name isn't in the OpenStreetMap list -- copy them from Google Maps")
        lat, lng = match["lat"], match["lng"]
        sources.append({"label": "OpenStreetMap location", "url": match["osm"]})
    if not sources:
        raise ValueError("needs at least one source link")
    if get("type") not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    if get("emergency_24x7").lower() not in YES_NO:
        raise ValueError("emergency_24x7 must be yes, no or unknown")
    specs = [s.strip() for s in get("specialties").split(";") if s.strip()]
    bad = set(specs) - set(SPECIALTIES)
    if bad:
        raise ValueError(f"unknown specialties {sorted(bad)}; use only {list(SPECIALTIES)}")
    emp = YES_NO.get(get("aarogyasri").lower(), "bad")
    if emp == "bad":
        raise ValueError("aarogyasri must be yes, no or unknown")
    evidence = get("aarogyasri_evidence") or None
    if emp is not None and evidence not in ("official", "reported"):
        raise ValueError("aarogyasri yes/no needs aarogyasri_evidence: official (hospital or govt site) or reported")
    entry = {
        "name": name, "locality": get("locality") or "Hyderabad", "lat": float(lat), "lng": float(lng),
        "type": get("type"), "specialties": specs, "trauma_level": int(get("trauma_level") or 0),
        "emergency_24x7": YES_NO[get("emergency_24x7").lower()],
        "aarogyasri_empanelled": emp, "aarogyasri_evidence": evidence if emp is not None else None,
    }
    if get("phone"):
        digits = re.sub(r"[^\d+]", "", get("phone"))
        if not digits.startswith("+"):
            digits = "+91" + digits.lstrip("0")
        if not get("phone_source_url").startswith("http"):
            raise ValueError("a phone number needs phone_source_url (where you found it)")
        entry["phone"] = {"number": digits, "kind": get("phone_kind") or "main",
                          "source": {"label": "Phone number source", "url": get("phone_source_url")}}
    if get("checked_on"):
        entry["checked_on"] = get("checked_on")
    if get("verified_by_phone").lower() == "yes":
        entry["data_level"] = "phone_verified"
    entry["sources"] = sources
    return entry


def write(data: dict) -> None:
    """Same layout as the hand-written file: one field per line, one source per line."""
    blocks = []
    for h in data["hospitals"]:
        lines = [f'      {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in h.items() if k != "sources"]
        srcs = ",\n".join(f"        {json.dumps(s, ensure_ascii=False)}" for s in h["sources"])
        lines.append(f'      "sources": [\n{srcs}\n      ]')
        blocks.append("    {\n" + ",\n".join(lines) + "\n    }")
    head = {k: v for k, v in data.items() if k != "hospitals"}
    head_lines = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in head.items())
    REAL_FILE.write_text("{\n" + head_lines + ',\n  "hospitals": [\n' + ",\n".join(blocks) + "\n  ]\n}\n", encoding="utf-8")


def main(path: str) -> int:
    data = json.loads(REAL_FILE.read_text(encoding="utf-8"))
    by_name = {norm(h["name"]): i for i, h in enumerate(data["hospitals"])}
    osm = osm_lookup()
    added = updated = 0
    with open(path, encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel adds a BOM
        for n, row in enumerate(csv.DictReader(f), start=2):
            try:
                entry = parse_row(row, osm)
            except (ValueError, KeyError) as e:
                print(f"row {n}: skipped -- {e}")
                continue
            key = norm(entry["name"])
            if key in by_name:
                data["hospitals"][by_name[key]] = entry
                updated += 1
            else:
                by_name[key] = len(data["hospitals"])
                data["hospitals"].append(entry)
                added += 1
    try:
        validate_real(data)
    except AssertionError as e:
        print(f"Nothing written: {e}")
        return 1
    write(data)
    print(f"{added} added, {updated} updated -> {REAL_FILE.name} ({len(data['hospitals'])} researched hospitals). "
          "Now run: python data/seed_facilities.py")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
