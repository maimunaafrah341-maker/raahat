"""Examples under the mic: a sentence to say and three to tap, in all four languages. Tapping one goes
through the same path as a described emergency, and nothing picks an area for the person."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.i18n import STRINGS  # noqa: E402
from backend.triage import INJURIES  # noqa: E402

WEB = ROOT / "frontend" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
KEYS = ["ex.say", "ex.label", "ex.fracture", "ex.chest", "ex.pregnancy", "area.needed"]


def test_every_example_string_exists_in_all_four_languages():
    for lang in ("en", "hi", "te", "ur"):
        for key in KEYS:
            assert STRINGS[lang].get(key, "").strip(), (lang, key)
        assert len(STRINGS[lang]["ex.chest"]) <= 40, lang  # short enough to be a chip


def test_examples_are_real_emergencies():
    block = APP_JS[APP_JS.index("const EXAMPLES"):APP_JS.index("function renderExamples")]
    found = dict(re.findall(r'key: "(\w+)", injury: "(\w+)"', block))
    assert found == {"fracture": "fracture", "chest": "chest_pain", "pregnancy": "pregnancy_problem"}
    assert all(i in INJURIES for i in found.values())


def test_a_tapped_example_takes_the_described_emergency_path():
    handler = APP_JS[APP_JS.index("function onExample"):APP_JS.index("function syncExamples")]
    assert "applyUnderstanding(" in handler and "area: null" in handler  # same path, never an invented area
    assert "state.understood.knowPlace = !!searchOrigin()" in handler
    assert "api(" not in handler  # works without the AI or a signal


def test_no_default_area_and_search_asks_for_one():
    assert '$("locality").value = "Charminar"' not in APP_JS
    origin = APP_JS[APP_JS.index("function searchOrigin"):APP_JS.index("function askForArea")]
    assert "|| null" in origin
    search = APP_JS[APP_JS.index("async function runSearch"):]
    assert re.search(r"if \(!origin\) \{ askForArea\(\); return; \}", search[:300])


def test_examples_sit_under_the_mic_and_hide_with_results():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert html.index('id="mic-btn"') < html.index('id="examples"') < html.index('id="pics"')
    assert 'function syncExamples() { $("examples").hidden = !$("results").hidden; }' in APP_JS
    assert APP_JS.count("syncExamples();") >= 3  # search, offline list, new emergency
