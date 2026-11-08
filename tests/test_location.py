"""'Use my location': every outcome has a short message in all four languages, and the coordinates
are never kept on the phone or sent anywhere but the search."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.i18n import STRINGS  # noqa: E402

GEO_KEYS = ["flow.locating", "flow.located", "flow.located_near", "flow.geo_denied", "flow.geo_timeout",
            "flow.geo_unavailable"]
APP_JS = (ROOT / "frontend/web/app.js").read_text(encoding="utf-8")


def _handler():
    start = APP_JS.index("const GEO_TIMEOUT_MS")
    return APP_JS[start:APP_JS.index("function searchOrigin", start)]


def test_every_location_message_exists_in_all_four_languages():
    for lang in ("en", "hi", "te", "ur"):
        for key in GEO_KEYS:
            assert STRINGS[lang].get(key, "").strip(), (lang, key)
        assert "{area}" in STRINGS[lang]["flow.located_near"], lang


def test_the_handler_uses_each_message_and_falls_back_to_the_area_box():
    h = _handler()
    for key in GEO_KEYS:
        assert f'"{key}"' in h, key
    assert "PERMISSION_DENIED" in h and "TIMEOUT" in h
    assert '$("locality").focus()' in h
    assert re.search(r"timeout:\s*GEO_TIMEOUT_MS", h)


def test_the_location_is_not_stored():
    h = _handler()
    assert "store.set" not in h and "localStorage" not in h and "sessionStorage" not in h
    assert re.search(r'track\("action", "geo_used"\)', h)  # only that it was used, not where

