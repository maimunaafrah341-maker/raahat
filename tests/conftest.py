import pytest


@pytest.fixture(autouse=True)
def no_real_gnani_calls(monkeypatch):
    """The real key in .env must never be used by a test: that would spend credits. Tests that need
    Gnani set a fake key and fake the network."""
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
