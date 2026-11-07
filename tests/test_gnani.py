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
    calls.reply = FakeResponse(content=b"RIFF\x00\x00\x00\x00WAVEdata\x00\x00\x00\x00\x01\x00")
    assert gnani.synthesize("नमस्ते", "hi").startswith(b"RIFF")
    url, kw = calls[0]
    assert url == "https://api.vachana.ai/api/v1/tts/inference"
    assert kw["json"]["model"] == "timbre-v2.5" and kw["json"]["voice"] == "Ambuja"
    assert kw["json"]["language"] == "hi-IN" and kw["json"]["audio_config"]["container"] == "wav"


@pytest.mark.parametrize("reply, message", [
    (FakeResponse(status=401), "API key rejected"),
    (FakeResponse(status=402), "out of credits"),
    (FakeResponse(status=429), "rate limited"),
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


WAV = b"RIFF" + b"\x00" * 40
HEARD = {"injury": "fracture", "situations": [], "conditions": [], "life_threatening_signs": False,
         "area": "Ameerpet", "summary": "Arm may be broken", "language": "te", "model": "gemini-x"}


def _post_audio(lang):
    from backend.app import app
    return app.test_client().post(f"/api/understand_audio?language={lang}", data=WAV,
                                  headers={"Content-Type": "audio/wav"})


@pytest.fixture
def route(monkeypatch):
    """Fake Gnani's transcription and both Gemini steps; record which ones ran."""
    from backend import app as app_module
    monkeypatch.setenv("GNANI_API_KEY", KEY)
    ran = []

    def fake_transcribe(audio, lang, mime):
        ran.append(("gnani", lang))
        if route_state["gnani_fails"]:
            raise gnani.GnaniError("HTTP 429 (rate limited)")
        return "నా చేయి విరిగింది, అమీర్‌పేట్"

    def fake_understand(text):
        ran.append(("gemini_text", text))
        return dict(HEARD)

    def fake_understand_audio(audio, mime, hint):
        ran.append(("gemini_audio", hint))
        return {**HEARD, "transcript": "heard by gemini"}

    route_state = {"gnani_fails": False}
    monkeypatch.setattr(gnani, "transcribe", fake_transcribe)
    monkeypatch.setattr(app_module, "understand", fake_understand)
    monkeypatch.setattr(app_module, "understand_audio", fake_understand_audio)
    return ran, route_state


def test_telugu_voice_is_heard_by_gnani_then_understood_by_gemini(route):
    ran, _ = route
    res = _post_audio("te").get_json()
    assert res["stt_provider"] == "gnani" and res["stt_model"] == "prisma-v3.0"
    assert res["transcript"] == "నా చేయి విరిగింది, అమీర్‌పేట్" and res["injury"] == "fracture"
    assert ran == [("gnani", "te"), ("gemini_text", "నా చేయి విరిగింది, అమీర్‌పేట్")]


def test_gnani_failure_falls_back_to_gemini_listening(route):
    ran, state = route
    state["gnani_fails"] = True
    res = _post_audio("hi").get_json()
    assert res["stt_provider"] == "gemini" and res["transcript"] == "heard by gemini"
    assert [r[0] for r in ran] == ["gnani", "gemini_audio"]


def test_urdu_never_goes_to_gnani(route):
    ran, _ = route
    assert _post_audio("ur").get_json()["stt_provider"] == "gemini"
    assert [r[0] for r in ran] == ["gemini_audio"]


@pytest.fixture
def tts(monkeypatch):
    """Fake Timbre and the Gemini fallback; record which ran. Starts with an empty audio cache."""
    from backend import speech
    monkeypatch.setenv("GNANI_API_KEY", KEY)
    monkeypatch.setattr(speech, "_cache", type(speech._cache)())
    ran, state = [], {"gnani_fails": False}

    def fake_synthesize(text, lang):
        ran.append("gnani")
        if state["gnani_fails"]:
            raise gnani.GnaniError("no answer within 10 s")
        return b"RIFF gnani"

    def fake_gemini(text):
        ran.append("gemini")
        return b"RIFF gemini", "gemini-tts"

    monkeypatch.setattr(gnani, "synthesize", fake_synthesize)
    monkeypatch.setattr(speech, "_gemini_speak", fake_gemini)
    return speech, ran, state


def test_telugu_read_aloud_uses_timbre_and_says_so(tts):
    from backend.app import app, _speak_log
    speech, ran, _ = tts
    _speak_log.clear()
    res = app.test_client().post("/api/speak", json={"text": "108కి ఫోన్ చేయండి.", "language": "te"})
    assert res.status_code == 200 and res.data == b"RIFF gnani"
    assert res.headers["X-TTS-Provider"] == "gnani" and res.headers["X-TTS-Model"] == "timbre-v2.5"
    assert ran == ["gnani"]


def test_timbre_failure_falls_back_to_gemini(tts):
    speech, ran, state = tts
    state["gnani_fails"] = True
    audio, model = speech.speak("Press firmly on the wound.", "en")
    assert audio == b"RIFF gemini" and speech.provider(model) == "gemini"
    assert ran == ["gnani", "gemini"]


def test_urdu_read_aloud_never_goes_to_gnani(tts):
    speech, ran, _ = tts
    assert speech.provider(speech.speak("108 پر کال کریں", "ur")[1]) == "gemini"
    assert ran == ["gemini"]


def test_repeated_text_is_served_from_cache_with_its_provider(tts):
    speech, ran, _ = tts
    first = speech.speak("Call 108.", "hi")
    assert speech.speak("Call 108.", "hi") == first and ran == ["gnani"]


def test_streaming_wav_header_gets_the_real_length(calls):
    import io
    import struct
    import wave
    pcm = b"\x01\x00" * 24000  # one second at 24 kHz
    fmt = struct.pack("<HHIIHH", 1, 1, 24000, 48000, 2, 16)
    calls.reply = FakeResponse(content=b"RIFF\xff\xff\xff\xffWAVEfmt " + struct.pack("<I", 16) + fmt
                               + b"data\xff\xff\xff\xff" + pcm)
    with wave.open(io.BytesIO(gnani.synthesize("hello", "en"))) as w:
        assert w.getnframes() == 24000


def test_per_ip_cap_then_daily_cap(monkeypatch):
    monkeypatch.setattr(gnani, "LIMIT_PER_IP_HOUR", 3)
    monkeypatch.setattr(gnani, "LIMIT_PER_DAY", 5)
    assert [gnani.take_quota("1.1.1.1") for _ in range(4)] == [True, True, True, False]
    assert [gnani.take_quota("2.2.2.2") for _ in range(3)] == [True, True, False]  # day total 5 reached
    assert not gnani.take_quota("3.3.3.3")


def test_ip_cap_frees_up_after_an_hour_and_day_cap_resets_next_day(monkeypatch):
    monkeypatch.setattr(gnani, "LIMIT_PER_IP_HOUR", 1)
    clock = {"t": 1000.0}
    monkeypatch.setattr(gnani.time, "monotonic", lambda: clock["t"])
    assert gnani.take_quota("1.1.1.1") and not gnani.take_quota("1.1.1.1")
    clock["t"] += 3601
    assert gnani.take_quota("1.1.1.1")
    monkeypatch.setattr(gnani, "LIMIT_PER_DAY", 1)
    gnani._today.update(date="2000-01-01", count=1)  # yesterday's total doesn't count today
    assert gnani.take_quota("9.9.9.9")


def test_zero_turns_gnani_off(monkeypatch):
    monkeypatch.setattr(gnani, "LIMIT_PER_DAY", 0)
    assert not gnani.take_quota("1.1.1.1")


def test_over_the_cap_voice_quietly_uses_gemini(route, monkeypatch):
    ran, _ = route
    monkeypatch.setattr(gnani, "LIMIT_PER_IP_HOUR", 1)
    assert _post_audio("te").get_json()["stt_provider"] == "gnani"
    res = _post_audio("te")
    assert res.status_code == 200 and res.get_json()["stt_provider"] == "gemini"
    assert [r[0] for r in ran] == ["gnani", "gemini_text", "gemini_audio"]


def test_over_the_cap_read_aloud_quietly_uses_gemini_and_cache_is_free(tts, monkeypatch):
    from backend.app import app, _speak_log
    speech, ran, _ = tts
    _speak_log.clear()
    monkeypatch.setattr(gnani, "LIMIT_PER_DAY", 1)
    client = app.test_client()
    say = lambda text: client.post("/api/speak", json={"text": text, "language": "te"})
    assert say("ఒకటి.").headers["X-TTS-Provider"] == "gnani"
    assert say("ఒకటి.").headers["X-TTS-Provider"] == "gnani"   # repeat: from the cache, no call counted
    res = say("రెండు.")
    assert res.status_code == 200 and res.headers["X-TTS-Provider"] == "gemini"
    assert ran == ["gnani", "gemini"]


def test_silence_is_an_empty_transcript_not_an_error(calls):
    calls.reply = FakeResponse(json_body={"success": True, "request_id": "x", "transcript": ""})
    assert gnani.transcribe(b"RIFF....", "te") == ""


def test_silence_says_nothing_heard_without_asking_gemini(route, monkeypatch):
    ran, _ = route
    monkeypatch.setattr(gnani, "transcribe", lambda audio, lang, mime: ran.append(("gnani", lang)) or "")
    res = _post_audio("te").get_json()
    assert res["transcript"] == "" and res["stt_provider"] == "gnani"
    assert ran == [("gnani", "te")]  # no Gemini text step, no Gemini listening retry


def test_hints_come_from_the_config_file_within_the_api_limits(monkeypatch, tmp_path):
    import json
    (tmp_path / "localities.json").write_text(json.dumps([{"name": "Ameerpet"}, {"name": "108"}]), encoding="utf-8")
    cfg = {"enabled": True, "topic": "x" * 2000, "include_localities": True, "keyterms": ["108", " NIMS ", ""] + [f"t{i}" for i in range(300)]}
    (tmp_path / "gnani_context.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(gnani, "DATA_DIR", tmp_path)
    ctx = gnani.load_context()
    assert len(ctx["topic"]) == 1600 and len(ctx["keyterms"]) == 200
    assert ctx["keyterms"][:2] == ["108", "NIMS"] and ctx["keyterms"].count("108") == 1
    cfg["enabled"] = False
    (tmp_path / "gnani_context.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert gnani.load_context() == {}


def test_hints_are_sent_as_a_json_list_when_enabled(calls, monkeypatch):
    import json
    monkeypatch.setattr(gnani, "CONTEXT", {"topic": "emergency", "keyterms": ["ఆరోగ్యశ్రీ", "NIMS"]})
    calls.reply = FakeResponse(json_body={"success": True, "transcript": "ok"})
    gnani.transcribe(b"RIFF....", "te")
    data = calls[0][1]["data"]
    assert data["topic"] == "emergency" and json.loads(data["keyterms"]) == ["ఆరోగ్యశ్రీ", "NIMS"]
    monkeypatch.setattr(gnani, "CONTEXT", {})
    gnani.transcribe(b"RIFF....", "te")
    assert "keyterms" not in calls[1][1]["data"]
