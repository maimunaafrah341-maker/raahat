"""Fetch every hospital in Greater Hyderabad from OpenStreetMap -> data/hospitals_osm.json.

These are UNCHECKED: OpenStreetMap is community-edited and says nothing reliable about emergency
capability. The app lists them only after the researched hospitals, labelled "not yet checked --
call first", so a person anywhere in the city still sees hospitals near them.

Run:  python data/fetch_osm_hospitals.py      (then re-seed: python data/seed_facilities.py)
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent / "hospitals_osm.json"
REAL = Path(__file__).resolve().parent / "hospitals_real.json"
BBOX = (17.20, 78.20, 17.65, 78.75)  # south, west, north, east: GHMC and the outer ring
# The main Overpass server is often busy (504); the public mirrors serve the same data.
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]

# Not places to take an emergency: animal, dental, alternative-medicine, diagnostics-only, cosmetic.
EXCLUDE = re.compile(r"veterin|animal|pet\b|dental|dentist|ayurved|homoeo|homeo|unani|naturo|nature cure|"
                     r"siddha|yoga|diagnostic|scan|imaging|lab\b|labs\b|ivf|fertility|skin|hair|cosmetic|"
                     r"physio|rehab|de-?addiction|blood bank|pharmacy|medical store|optical|hearing|"
                     # single-organ centres that won't take a general emergency
                     r"\beye\b|vision|netralaya|\bent\b|kidney|dialysis|urology|"
                     r"^(?!.*hospital).*clinic", re.I)


TILE_CACHE = Path(__file__).resolve().parent / ".osm_tiles"  # finished tiles, so a rerun resumes


def fetch() -> list[dict]:
    """The city in 3x3 tiles: small queries get through when the public servers are busy. Each tile is
    retried for a few rounds and saved once fetched, so a rerun only fetches what's missing."""
    import time
    s, w, n, e = BBOX
    lat_steps = [s + (n - s) * i / 3 for i in range(4)]
    lng_steps = [w + (e - w) * i / 3 for i in range(4)]
    tiles = [(lat_steps[i], lng_steps[j], lat_steps[i + 1], lng_steps[j + 1]) for i in range(3) for j in range(3)]
    TILE_CACHE.mkdir(exist_ok=True)
    elements = {}
    for round_ in range(4):
        missing = [t for t in tiles if not (TILE_CACHE / f"{'_'.join(f'{x:.3f}' for x in t)}.json").exists()]
        if not missing:
            break
        print(f"round {round_ + 1}: {len(missing)} of {len(tiles)} tiles to fetch")
        for tile in missing:
            try:
                got = _fetch_tile(*tile)
            except Exception:  # noqa: BLE001 -- all mirrors busy for this tile; next round
                continue
            (TILE_CACHE / f"{'_'.join(f'{x:.3f}' for x in tile)}.json").write_text(json.dumps(got), encoding="utf-8")
        time.sleep(20 * (round_ + 1))
    for t in tiles:
        path = TILE_CACHE / f"{'_'.join(f'{x:.3f}' for x in t)}.json"
        if not path.exists():
            raise SystemExit(f"Tile {t} could not be fetched (servers busy). Run again later; finished tiles are kept.")
        for el in json.loads(path.read_text(encoding="utf-8")):
            elements[(el["type"], el["id"])] = el
    return list(elements.values())


def _fetch_tile(s: float, w: float, n: float, e: float) -> list[dict]:
    query = f"""[out:json][timeout:80];
(node["amenity"="hospital"]({s},{w},{n},{e});
 way["amenity"="hospital"]({s},{w},{n},{e});
 relation["amenity"="hospital"]({s},{w},{n},{e}););
out center tags;"""
    last = None
    for url in OVERPASS:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": "Raahat-prototype/1.0 (emergency care finder)"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)["elements"]
        except Exception as err:  # noqa: BLE001 -- busy server: try the next mirror
            print(f"{url}: {err}")
            last = err
    raise last


def norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("hospitals", "hospital"))


def phone_of(tags: dict) -> str | None:
    raw = tags.get("contact:phone") or tags.get("phone") or ""
    for part in re.split(r"[;,/]", raw):
        digits = re.sub(r"\D", "", part)
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        digits = digits.lstrip("0")
        if len(digits) == 10:
            return "+91" + digits
    return None


def main() -> None:
    real = json.loads(REAL.read_text(encoding="utf-8"))["hospitals"]
    seen = [(norm(h["name"]), h["lat"], h["lng"]) for h in real]
    out, skipped = [], {"no name": 0, "not emergency care": 0, "already researched": 0, "duplicate": 0}
    for el in fetch():
        tags = el.get("tags", {})
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if not name or lat is None or not re.search(r"[A-Za-z]", name):
            skipped["no name"] += 1
            continue
        if EXCLUDE.search(name) or tags.get("healthcare:speciality", "") in ("dentistry", "veterinary"):
            skipped["not emergency care"] += 1
            continue
        key = norm(name)
        # Same name within ~400 m, or any hospital within ~60 m, is the same place.
        near = [k for k, a, b in seen if abs(a - lat) < 0.004 and abs(b - lng) < 0.004]
        if any(k == key or key in k or k in key for k in near) or \
           any(abs(a - lat) < 0.0006 and abs(b - lng) < 0.0006 for _, a, b in seen):
            skipped["already researched" if any(abs(h["lat"] - lat) < 0.004 and abs(h["lng"] - lng) < 0.004
                                                 for h in real) else "duplicate"] += 1
            continue
        seen.append((key, lat, lng))
        osm_url = f"https://www.openstreetmap.org/{el['type']}/{el['id']}"
        entry = {
            "name": name,
            "locality": tags.get("addr:suburb") or tags.get("addr:city") or "Hyderabad",
            "lat": round(lat, 7), "lng": round(lng, 7),
            "osm": osm_url,
            "operator_type": tags.get("operator:type") or tags.get("healthcare:operator") or None,
            "osm_emergency": tags.get("emergency"),  # "yes"/"no" if a mapper recorded it; never trusted alone
            "website": tags.get("website") or tags.get("contact:website"),
        }
        phone = phone_of(tags)
        if phone:
            entry["phone"] = phone
        out.append(entry)
    out.sort(key=lambda h: h["name"].lower())
    OUT.write_text(json.dumps({"fetched_on": date.today().isoformat(), "source": "OpenStreetMap contributors (ODbL)",
                               "bbox": BBOX, "hospitals": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} hospitals written to {OUT.name}; skipped {skipped}")


if __name__ == "__main__":
    sys.exit(main())
