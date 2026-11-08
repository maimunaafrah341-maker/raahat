"""Every action the page tracks must be one the server accepts, or the event is silently dropped (400)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import analytics  # noqa: E402


def test_every_tracked_action_is_accepted():
    app_js = (ROOT / "frontend" / "web" / "app.js").read_text(encoding="utf-8")
    tracked = set(re.findall(r'track\("action", "([a-z_0-9]+)"', app_js))
    assert {"geo_used", "area_picked", "example_used"} <= tracked
    assert tracked <= set(analytics.ACTIONS), tracked - set(analytics.ACTIONS)


def test_the_new_actions_are_stored(monkeypatch):
    from backend import app as app_module
    logged = []
    monkeypatch.setattr(app_module.analytics, "log", lambda kind, **kw: logged.append((kind, kw.get("value"))))
    client = app_module.app.test_client()
    for value in ("area_picked", "example_used"):
        res = client.post("/api/event", json={"kind": "action", "value": value, "session": "s1"})
        assert res.status_code < 300, (value, res.status_code, res.get_data(as_text=True))
    assert ("action", "area_picked") in logged and ("action", "example_used") in logged
