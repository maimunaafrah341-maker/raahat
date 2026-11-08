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


def _search(monkeypatch, tmp_path, capsys, **body):
    from backend import analytics, app as app_module
    monkeypatch.setattr(analytics, "DATABASE_URL", None)
    db = tmp_path / f"analytics_{len(list(tmp_path.iterdir()))}.db"
    monkeypatch.setattr(analytics, "SQLITE_PATH", db)
    monkeypatch.setattr(analytics, "_ready", False)
    capsys.readouterr()
    res = app_module.app.test_client().post("/api/triage", json={"injury": "fracture", "session": "s1", **body})
    assert res.status_code == 200
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("RAAHAT_EVENT")]
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("SELECT * FROM events")
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    finally:
        conn.close()
    return printed, rows


def test_a_search_from_the_phones_location_logs_nothing_about_where(monkeypatch, tmp_path, capsys):
    # GPS near Charminar, with a stale area name the page might also send: neither may be logged.
    for area in (None, "Charminar", "Abids"):
        printed, rows = _search(monkeypatch, tmp_path, capsys, lat=17.36183, lng=78.47467, area=area)
        assert len(printed) == 1 and len(rows) == 1
        everything = printed[0] + repr(rows)
        for leak in ("17.36", "78.47", "17.3618", "78.4746", "Charminar", "Abids"):
            assert leak not in everything, (area, leak)
        assert rows[0]["area"] is None and rows[0]["kind"] == "search"


def test_a_picked_area_is_still_logged_by_name(monkeypatch, tmp_path, capsys):
    from backend.app import AREA_COORDS
    lat, lng = AREA_COORDS["Abids"]
    printed, rows = _search(monkeypatch, tmp_path, capsys, lat=lat, lng=lng, area="Abids")
    assert rows[0]["area"] == "Abids"
    assert f"{lat}" not in printed[0] and f"{lng}" not in printed[0]  # the name, never the coordinates
