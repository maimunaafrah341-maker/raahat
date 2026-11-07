"""Speech to text (Prisma) and text to speech (Timbre) with Gnani's Vachana API, for Telugu, Hindi and English.

Docs: https://docs.gnani.ai (api/STT/speech-to-text, api/TTS/tts-inference). Gnani has no Urdu, so
callers check supports() first and keep Gemini for everything else, and as the fallback when this fails.
"""
import json
import os
import struct
import threading
import time
from collections import deque
from pathlib import Path

import requests

BASE_URL = "https://api.vachana.ai"
STT_MODEL = "prisma-v3.0"   # takes several languages at once, so Telugu or Hindi mixed with English works
TTS_MODEL = "timbre-v2.5"   # the docs' recommended model; v2.0 is deprecated
STT_TIMEOUT_S = 12          # someone is waiting in an emergency: fall back to Gemini rather than hang
TTS_TIMEOUT_S = 10
MAX_AUDIO_S = 30            # the REST speech-to-text endpoint rejects longer clips

LANGS = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}
# What the person may speak: their language plus English, which most people here mix in.
STT_LANGUAGES = {"te": "te-IN,en-IN", "hi": "hi-IN,en-IN", "en": "en-IN"}
# Timbre v2.5 voices are tied to a preferred language (docs: api/TTS/available-voices). Calm and clear,
# for someone hearing first aid in an emergency: Suhana "calm, soothing voice with confidence",
# Ambuja "clear, composed", Kaveri "firm voice". All female, like the Gemini fallback voice.
VOICES = {"te": "Suhana", "hi": "Ambuja", "en": "Kaveri"}
# Prisma picks the format from the file name, so the upload needs the right extension.
# Hints that help Prisma hear our words: area and hospital names, "Aarogyasri", "108". The list
# lives in data/gnani_context.json so it can be edited without touching code.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_KEYTERMS = 200  # the API's limit


def load_context() -> dict:
    """{"topic": str, "keyterms": [...]} to send with each transcription, or {} if hints are turned off."""
    cfg = json.loads((DATA_DIR / "gnani_context.json").read_text(encoding="utf-8"))
    if not cfg.get("enabled", True):
        return {}
    terms = list(cfg.get("keyterms", []))
    if cfg.get("include_localities"):
        terms += [loc["name"] for loc in json.loads((DATA_DIR / "localities.json").read_text(encoding="utf-8"))]
    terms = list(dict.fromkeys(t.strip() for t in terms if t.strip()))[:MAX_KEYTERMS]
    return {"topic": cfg["topic"][:1600], "keyterms": terms}


CONTEXT = load_context()

# Credit protection for a public link. Over either cap, callers quietly use Gemini instead.
# One visitor in a real emergency makes ~15 calls in an hour (a couple of voice descriptions, two or
# three first-aid cards read aloud at ~3 pieces each), so 40 an hour per IP never gets in their way
# but stops one person or script from draining the account. The daily cap is the real backstop,
# because an IP limit is easy to get around (mobile networks, VPNs). 0 turns Gnani off.
LIMIT_PER_IP_HOUR = int(os.environ.get("GNANI_LIMIT_PER_IP_HOUR", "40"))
LIMIT_PER_DAY = int(os.environ.get("GNANI_LIMIT_PER_DAY", "300"))
# Counters live in this process's memory: one gunicorn worker (start.sh), so all threads share them.
# A restart, a redeploy or Render's free-plan sleep after 15 idle minutes resets them.
_lock = threading.Lock()
_per_ip: dict[str, deque] = {}
_today = {"date": "", "count": 0}

EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
              "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac", "audio/mp4": "m4a"}


class GnaniError(Exception):
    """Gnani didn't give a usable answer. The message is safe to log: it never contains the key."""


def take_quota(client: str | None) -> bool:
    """Count one Gnani call for this client (IP). False, and nothing counted, if a cap is reached."""
    now, date = time.monotonic(), time.strftime("%Y-%m-%d", time.gmtime())
    with _lock:
        if _today["date"] != date:
            _today.update(date=date, count=0)
        if _today["count"] >= LIMIT_PER_DAY:
            return False
        calls = _per_ip.setdefault(client or "?", deque())
        while calls and now - calls[0] > 3600:
            calls.popleft()
        if len(calls) >= LIMIT_PER_IP_HOUR:
            return False
        calls.append(now)
        _today["count"] += 1
        if len(_per_ip) > 5000:  # forget visitors idle for an hour
            for ip in [ip for ip, c in _per_ip.items() if not c or now - c[-1] > 3600]:
                del _per_ip[ip]
        return True


def _key() -> str | None:
    return os.environ.get("GNANI_API_KEY") or None


def supports(lang: str | None) -> bool:
    """True when Gnani can handle this language and a key is set."""
    return lang in LANGS and _key() is not None


def _post(path: str, timeout: float, **kwargs) -> requests.Response:
    """POST with the key header; turn timeouts, network errors and error statuses into GnaniError."""
    key = _key()
    if not key:
        raise GnaniError("GNANI_API_KEY is not set")
    try:
        resp = requests.post(f"{BASE_URL}{path}", headers={"X-API-Key-ID": key, **kwargs.pop("headers", {})},
                             timeout=timeout, **kwargs)
    except requests.exceptions.Timeout:
        raise GnaniError(f"no answer within {timeout:g} s") from None
    except requests.exceptions.RequestException as err:
        raise GnaniError(f"network error: {type(err).__name__}") from None
    if resp.status_code != 200:
        reason = {401: "API key rejected", 402: "out of credits", 429: "rate limited"}.get(resp.status_code, "error")
        raise GnaniError(f"HTTP {resp.status_code} ({reason})")
    return resp


def transcribe(audio: bytes, lang: str, mime_type: str = "audio/wav") -> str:
    """Recorded audio -> the words spoken, in the script they were spoken in (English words stay English).
    "" if the recording held no speech."""
    if lang not in LANGS:
        raise GnaniError(f"language {lang!r} is not supported")
    ext = EXTENSIONS.get(mime_type)
    if not ext:
        raise GnaniError(f"audio type {mime_type} is not supported")
    resp = _post("/stt/v3", STT_TIMEOUT_S,
                 files={"audio_file": (f"recording.{ext}", audio, mime_type)},
                 data={"model": STT_MODEL, "language_code": STT_LANGUAGES[lang], "format": "codemix", **_context_fields()})
    try:
        body = resp.json()
    except ValueError:
        raise GnaniError("answer was not JSON") from None
    if not body.get("success"):
        raise GnaniError("transcription failed")
    # Silence is not an error (docs): an empty transcript means nobody spoke, so say so at once
    # instead of asking Gemini to listen to the same silence.
    return (body.get("transcript") or "").strip()


def _context_fields() -> dict:
    if not CONTEXT:
        return {}
    return {"topic": CONTEXT["topic"], "keyterms": json.dumps(CONTEXT["keyterms"], ensure_ascii=False)}


def synthesize(text: str, lang: str) -> bytes:
    """Text -> WAV audio read in the default voice for that language."""
    if lang not in LANGS:
        raise GnaniError(f"language {lang!r} is not supported")
    resp = _post("/api/v1/tts/inference", TTS_TIMEOUT_S, json={
        "text": text, "voice": VOICES[lang], "model": TTS_MODEL, "language": LANGS[lang],
        "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"}})
    if resp.content[:4] != b"RIFF":
        raise GnaniError("answer was not WAV audio")
    return _with_real_length(resp.content)


def _with_real_length(wav: bytes) -> bytes:
    """Timbre sends a streaming WAV header whose sizes are 0xFFFFFFFF ("unknown"), which reads as a
    25-hour clip. Write in the real sizes so browsers know when each piece ends and play the next."""
    data_at = wav.find(b"data", 12)
    if data_at < 0:
        raise GnaniError("answer was not WAV audio")
    body = len(wav) - (data_at + 8)
    return (wav[:4] + struct.pack("<I", len(wav) - 8) + wav[8:data_at + 4]
            + struct.pack("<I", body) + wav[data_at + 8:])
