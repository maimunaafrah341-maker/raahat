"""Match the official PM-JAY registry (data/registry_pmjay.json) to the hospitals the app lists.

Writes data/registry_matches.json: for each registry hospital, the listed hospital it is the same place as,
if we can tell from the names alone. Matching is deliberately strict -- a wrong match would tell someone a
hospital takes Aarogyasri when it may not -- so a name shared by several branches of a chain ("Yashoda
Hospitals") is only matched when the branch (e.g. "Malakpet") appears in both. Unmatched hospitals stay as
they were; "not in our match" never means "not empanelled".

Run:  python data/match_registry.py      (then re-seed: python data/seed_facilities.py)
"""
import difflib
import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parent
REGISTRY, OSM, REAL = DIR / "registry_pmjay.json", DIR / "hospitals_osm.json", DIR / "hospitals_real.json"
LOCALITIES = DIR / "localities.json"
OUT = DIR / "registry_matches.json"

# Primary health centres are in the scheme but are not emergency hospitals; they're not in our list.
PRIMARY_CARE = re.compile(r"\b(u?phc|basti|dawakhana|sub ?centre|uphc)\b", re.I)
NOISE = re.compile(r"\b(the|a unit of .*|unit of .*|pvt|private|ltd|limited|llp|hospitals?|multi ?speciality|"
                   r"multispeciality|multi ?specialty|super ?speciality|super ?specialty|speciality|specialty|"
                   r"centre|center|and|research|institute|of|medical|sciences|care|clinic|nursing home|"
                   r"enterprises|india|healthcare|health)\b", re.I)


# Our researched hospitals, matched by hand (registry name -> our name). Checked one by one on 2026-10-24:
# the registry lists one KIMS, one Continental and one Kamineni Hospitals in the districts where ours are.
RESEARCHED = {
    "Osmania General Hospital": "Osmania General Hospital",
    "Gandhi Hospitals": "Gandhi Hospital",
    "Nims Hospitals": "Nizam's Institute of Medical Sciences (NIMS)",
    "Sarojini Devi Eye Hospital": "Sarojini Devi Eye Hospital",
    "Owaisi Hospital  And Research Center": "Owaisi Hospital and Research Centre",
    "Mahavir Hospital And Research Centre": "Mahavir Hospital and Research Centre",
    "Yashoda Hospitals - Somajiguda": "Yashoda Hospitals, Somajiguda",
    "Yashoda Hospital Malakpet": "Yashoda Hospitals, Malakpet",
    "Krishna Institute Of Medical Sciences Ltd": "KIMS Hospitals, Secunderabad",
    "Apollo Hospitals Enterprises Ltd Jubilee Hills": "Apollo Hospitals, Jubilee Hills",
    "Niloufer Hospital": "Niloufer Hospital (women and children)",
    "Government Hospital for Mental Care": "Institute of Mental Health, Erragadda",
    "M.N.J.Hospitals": "MNJ Institute of Oncology and Regional Cancer Centre",
    "BASAVATARAKAM INDO AMERICAN CANCER HOSPITAL and RESEARCH INSTITUTE": "Basavatarakam Indo-American Cancer Hospital",
    "CONTINENTAL HOSPITALS LIMITED": "Continental Hospitals, Gachibowli",
    "Kamineni Hospitals Pvt Ltd": "Kamineni Hospitals, LB Nagar",
}
# Names with several branches in the city: matched only when the branch is named on both sides.
CHAINS = re.compile(r"\b(yashoda|apollo|care|kims|krishna|kamineni|omega|pace|aig|rainbow|ankura|sunshine|"
                    r"agarwal|maxcure|medicover|citizens|star|aware|global|gleneagles|srikara|prasad|lotus|"
                    r"vijaya|sai|sri sai|raghavendra|venkateshwara|venkateswara|balaji|lakshmi|"
                    r"krishna|ramana|srinivasa|tirumala|life ?care|lifeline|life line|mother|amma)\b", re.I)
# Matches rejected after looking at them by hand (registry name -> listed name).
REJECT = {("Krishna Institute Of Medical Sciences Ltd", "Krishna Hospital")}
# Rough district areas, to catch two different hospitals that share a name. Hyderabad district is the
# compact core; the others surround it (Sangareddy to the far west, Medchal to the north).
CORE = (17.29, 78.37, 17.48, 78.57)


def in_district(district: str, lat: float, lng: float) -> bool:
    s, w, n, e = CORE
    inside_core = s <= lat <= n and w <= lng <= e
    deep_core = 17.34 <= lat <= 17.44 and 78.43 <= lng <= 78.53
    return {"Hyderabad": inside_core, "Sangareddy": lng < 78.40, "Medchal Malkajgiri": lat > 17.40,
            "Ranga Reddy": not deep_core}.get(district, True)


def norm(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    osm = json.loads(OSM.read_text(encoding="utf-8"))["hospitals"]
    real_names = {h["name"] for h in json.loads(REAL.read_text(encoding="utf-8"))["hospitals"]}
    places = [l["name"].lower() for l in json.loads(LOCALITIES.read_text(encoding="utf-8"))]
    places_rx = re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(places, key=len, reverse=True)) + r")\b")
    reg_by_name = {h["name"]: h for h in registry["hospitals"]}

    matches = []
    for reg_name, ours in RESEARCHED.items():
        assert reg_name in reg_by_name, f"not in registry any more: {reg_name}"
        assert ours in real_names, f"not one of our hospitals: {ours}"
        h = reg_by_name[reg_name]
        matches.append({"registry_name": reg_name, "district": h["district"], "type": h["type"],
                        "listed_kind": "researched", "listed_name": ours, "listed_ref": ours, "method": "by hand"})

    squashed = {p.replace(" ", ""): p for p in places}

    def places_in(name: str) -> set[str]:
        """Area names in a hospital name, spelt with or without spaces ("Kingkoti" = "King Koti")."""
        flat = re.sub(r"[^a-z]", "", name.lower())
        return set(places_rx.findall(name.lower())) | {p for sq, p in squashed.items() if len(sq) > 4 and sq in flat}

    listed = [dict(h, norm=norm(h["name"]), place=places_in(h["name"])) for h in osm]
    skipped = {"primary care": 0, "chain without branch": 0, "wrong district": 0}
    for h in registry["hospitals"]:
        if h["name"] in RESEARCHED:
            continue
        if PRIMARY_CARE.search(h["name"]):
            skipped["primary care"] += 1
            continue
        rn = norm(h["name"])
        if len(rn) < 3:
            continue
        rplace = places_in(h["name"])
        best, best_score = None, 0.0
        for item in listed:
            if not item["norm"]:
                continue
            score = difflib.SequenceMatcher(None, rn, item["norm"]).ratio()
            rflat, iflat = re.sub(r"[^a-z]", "", h["name"].lower()), re.sub(r"[^a-z]", "", item["name"].lower())
            shared = (rplace & item["place"]) or {p for p in item["place"] if p.replace(" ", "") in rflat}                 or {p for p in rplace if p.replace(" ", "") in iflat}
            if (rplace or item["place"]) and not shared:
                if rplace and item["place"]:
                    continue
                score -= 0.15  # one side names a branch, the other doesn't: weaker
            if score > best_score:
                best, best_score = item, score
        if not best or best_score < 0.88 or (h["name"], best["name"]) in REJECT:
            continue
        brand = re.sub(r"\(?\s*a unit of.*$", "", h["name"], flags=re.I)  # the company behind it isn't the brand
        if CHAINS.search(brand) and not (rplace and rplace & best["place"]):
            skipped["chain without branch"] += 1
            continue
        if not in_district(h["district"], best["lat"], best["lng"]):
            skipped["wrong district"] += 1
            continue
        matches.append({"registry_name": h["name"], "district": h["district"], "type": h["type"],
                        "listed_kind": "osm", "listed_name": best["name"], "listed_ref": best["osm"],
                        "method": "name", "score": round(best_score, 3)})
    by_ref: dict[str, dict] = {}  # one listed hospital can't be two registry hospitals
    for m in sorted(matches, key=lambda m: -m.get("score", 2)):
        by_ref.setdefault(m["listed_ref"], m)
    kept = sorted(by_ref.values(), key=lambda m: (m["listed_kind"], m["listed_name"].lower()))
    OUT.write_text(json.dumps({"registry_fetched_on": registry["fetched_on"], "source_url": registry["source_url"],
                               "matches": kept}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(registry['hospitals'])} registry hospitals; skipped {skipped}; {len(kept)} matched "
          f"({sum(m['listed_kind'] == 'researched' for m in kept)} researched by hand, "
          f"{sum(m['listed_kind'] == 'osm' for m in kept)} OpenStreetMap by name)")


if __name__ == "__main__":
    main()
