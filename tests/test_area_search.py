"""The area search box: spelling variants, alternate names, typos and Telugu/Hindi/Urdu script find the
right area (frontend/web/areas.js, run through node), and the page is wired so a search from the phone's
location never saves the leftover default area."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.i18n import STRINGS  # noqa: E402

WEB = ROOT / "frontend" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")

# query -> the area that must come first
FIRST = {
    "amee": "Ameerpet", "amirpet": "Ameerpet", "ameerpeth": "Ameerpet",
    "kukatpalli": "Kukatpally", "kukatpally": "Kukatpally", "kphb": "KPHB Colony",
    "kukatpally housing": "KPHB Colony", "lal bahadur": "LB Nagar", "l.b. nagar": "LB Nagar",
    "mehdipatnm": "Mehdipatnam", "hayatnagar": "Hayathnagar", "secbad": "Secunderabad",
    "charminaar": "Charminar", "old city": "Charminar", "panjagutta": "Punjagutta", "musapet": "Moosapet",
    "golkonda": "Golconda", "hitec city": "Hitech City", "tolichowki": "Tolichowki",
    "కూకట్‌పల్లి": "Kukatpally", "అమీర్‌పేట": "Ameerpet", "చార్మినార్": "Charminar",
    "दिलसुखनगर": "Dilsukhnagar", "कुकटपल्ली": "Kukatpally", "चारमीनार": "Charminar",
    "چارمینار": "Charminar", "کوکٹ پلی": "Kukatpally", "مہدی پٹنم": "Mehdipatnam",
}
NOTHING = ["zzzz", "london", "x", ""]

RUN = """
const A = require(process.argv[1]);
const idx = A.index(require(process.argv[2]));
const out = {};
for (const q of JSON.parse(process.argv[3])) out[q] = A.match(q, idx).map((m) => m.area.name);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def results():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    queries = list(FIRST) + NOTHING
    out = subprocess.run([node, "-e", RUN, str(WEB / "areas.js"), str(ROOT / "data" / "localities.json"),
                          json.dumps(queries, ensure_ascii=False)],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("query,area", FIRST.items())
def test_the_right_area_comes_first(results, query, area):
    assert results[query][:1] == [area], (query, results[query])


def test_nonsense_and_too_short_find_nothing(results):
    for q in NOTHING:
        assert results[q] == [], q


def test_never_more_than_six_choices(results):
    assert all(len(v) <= 6 for v in results.values())


def test_aliases_are_real_areas_and_names_unchanged():
    areas = json.loads((ROOT / "data" / "localities.json").read_text(encoding="utf-8"))
    names = [a["name"] for a in areas]
    assert len(names) == len(set(names)) == 106
    for a in areas:
        assert set(a) <= {"name", "zone", "lat", "lng", "aliases"}
        assert all(isinstance(x, str) and x.strip() for x in a.get("aliases", []))


def test_the_dropdown_is_gone_and_the_box_is_wired():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<select id="locality"' not in html
    assert 'id="area-search"' in html and 'role="combobox"' in html and '<input id="locality" type="hidden">' in html
    assert html.index('src="areas.js"') < html.index('src="app.js"')
    assert '"/areas.js"' in (WEB / "sw.js").read_text(encoding="utf-8")  # works offline too


def test_no_match_message_in_all_four_languages():
    for lang in ("en", "hi", "te", "ur"):
        assert STRINGS[lang].get("area.none", "").strip(), lang
        assert STRINGS[lang].get("area.placeholder", "").strip(), lang


def test_a_case_from_the_phones_location_saves_no_area():
    sync = APP_JS[APP_JS.index("function syncCase"):APP_JS.index("function newCase")]
    assert re.search(r'locality:\s*\$\("use-coords"\)\.checked\s*\?\s*null\s*:\s*\$\("locality"\)\.value', sync)
    assert "lat" not in sync and "lng" not in sync


def test_spoken_description_still_fills_the_area_the_same_way():
    # The spoken path sets #locality and fires "change"; the box follows from that change listener.
    assert '$("locality").value = res.area;' in APP_JS
    listener = APP_JS[APP_JS.index('$("locality").addEventListener("change"'):]
    assert "showChosenArea()" in listener[:400]
