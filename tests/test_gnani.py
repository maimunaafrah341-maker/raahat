"""Gnani speech to text and text to speech. Every network call is faked, so no credits are spent."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import gnani  # noqa: E402

KEY = "test-key-not-real"


class FakeResponse:
    def __init__(self, status=200, json_body=None, content=b""):
        self.status_code, self._json, self.content = status, json_body, content

    def json(self):
        if self._json is None:
            raise ValueError("not JSON")
        return self._json


@pytest.fixture
def calls(monkeypatch):
    """Record each request and answer with whatever the test puts in calls.reply."""
    monkeypatch.setenv("GNANI_API_KEY", KEY)

    class Calls(list):
        reply = FakeResponse()

    seen = Calls()

    def fake_post(url, **kwargs):
        seen.append((url, kwargs))
        if isinstance(seen.reply, Exception):
            raise seen.reply
        return seen.reply

    monkeypatch.setattr(gnani.requests, "post", fake_post)
    return seen


def test_supports_only_telugu_hindi_english_with_a_key(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", KEY)
    assert all(gnani.supports(lang) for lang in ("te", "hi", "en"))
    assert not gnani.supports("ur") and not gnani.supports(None)
    monkeypatch.delenv("GNANI_API_KEY")
    assert not gnani.supports("te")


def test_transcribe_sends_the_documented_request(calls):
    calls.reply = FakeResponse(json_body={"success": True, "transcript": " నా చేయి విరిగింది "})
    assert gnani.transcribe(b"RIFF....", "te") == "నా చేయి విరిగింది"
    url, kw = calls[0]
    assert url == "https://api.vachana.ai/stt/v3"
    assert kw["headers"]["X-API-Key-ID"] == KEY
    assert kw["files"]["audio_file"][0] == "recording.wav"
    assert kw["data"] == {"model": "prisma-v3.0", "language_code": "te-IN,en-IN", "format": "codemix"}
    assert kw["timeout"] == gnani.STT_TIMEOUT_S


def test_synthesize_uses_timbre_and_the_language_voice(calls):
    calls.reply = FakeResponse(content=b"RIFF\x00\x00WAVE")
    assert gnani.synthesize("नमस्ते", "hi").startswith(b"RIFF")
    url, kw = calls[0]
    assert url == "https://api.vachana.ai/api/v1/tts/inference"
    assert kw["json"]["model"] == "timbre-v2.5" and kw["json"]["voice"] == "Nalini"
    assert kw["json"]["language"] == "hi-IN" and kw["json"]["audio_config"]["container"] == "wav"


@pytest.mark.parametrize("reply, message", [
    (FakeResponse(status=401), "API key rejected"),
    (FakeResponse(status=402), "out of credits"),
    (FakeResponse(status=429), "rate limited"),
    (FakeResponse(json_body={"success": True, "transcript": ""}), "no speech"),
    (FakeResponse(json_body={"success": False, "error": {"message": "bad audio"}}), "transcription failed"),
    (FakeResponse(content=b"<html>"), "not JSON"),
    (requests.exceptions.Timeout(), "no answer within"),
    (requests.exceptions.ConnectionError(), "network error"),
])
def test_transcribe_failures_raise_a_clear_error_without_the_key(calls, reply, message):
    calls.reply = reply
    with pytest.raises(gnani.GnaniError, match=message) as err:
        gnani.transcribe(b"RIFF....", "en")
    assert KEY not in str(err.value)


def test_synthesize_rejects_a_reply_that_is_not_audio(calls):
    calls.reply = FakeResponse(content=b'{"error": "too long"}')
    with pytest.raises(gnani.GnaniError, match="not WAV"):
        gnani.synthesize("hello", "en")


def test_nothing_is_sent_without_a_key_or_for_urdu_or_webm(calls, monkeypatch):
    with pytest.raises(gnani.GnaniError, match="not supported"):
        gnani.transcribe(b"x", "ur")
    with pytest.raises(gnani.GnaniError, match="audio type"):
        gnani.transcribe(b"x", "te", "audio/webm")
    monkeypatch.delenv("GNANI_API_KEY")
    with pytest.raises(gnani.GnaniError, match="not set"):
        gnani.synthesize("hello", "en")
    assert not calls
