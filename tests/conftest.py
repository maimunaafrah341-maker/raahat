import pytest

from backend import gnani


@pytest.fixture(autouse=True)
def no_real_gnani_calls(monkeypatch):
    """The real key in .env must never be used by a test: that would spend credits. Tests that need
    Gnani set a fake key and fake the network."""
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    # Fresh call counters for every test, so caps never carry over from another test.
    monkeypatch.setattr(gnani, "_per_ip", {})
    monkeypatch.setattr(gnani, "_today", {"date": "", "count": 0})
    monkeypatch.setattr(gnani, "CONTEXT", {})  # hints off unless a test sets them, whatever the config says
