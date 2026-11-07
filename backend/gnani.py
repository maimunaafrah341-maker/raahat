"""Speech to text (Prisma) and text to speech (Timbre) with Gnani's Vachana API, for Telugu, Hindi and English.

Docs: https://docs.gnani.ai (api/STT/speech-to-text, api/TTS/tts-inference). Gnani has no Urdu, so
callers check supports() first and keep Gemini for everything else, and as the fallback when this fails.
"""
import os
import struct

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
EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
              "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac", "audio/mp4": "m4a"}


class GnaniError(Exception):
    """Gnani didn't give a usable answer. The message is safe to log: it never contains the key."""


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
    """Recorded audio -> the words spoken, in the script they were spoken in (English words stay English)."""
    if lang not in LANGS:
        raise GnaniError(f"language {lang!r} is not supported")
    ext = EXTENSIONS.get(mime_type)
    if not ext:
        raise GnaniError(f"audio type {mime_type} is not supported")
    resp = _post("/stt/v3", STT_TIMEOUT_S,
                 files={"audio_file": (f"recording.{ext}", audio, mime_type)},
                 data={"model": STT_MODEL, "language_code": STT_LANGUAGES[lang], "format": "codemix"})
    try:
        body = resp.json()
    except ValueError:
        raise GnaniError("answer was not JSON") from None
    transcript = (body.get("transcript") or "").strip() if body.get("success") else ""
    if not transcript:
        raise GnaniError("no speech was heard" if body.get("success") else "transcription failed")
    return transcript


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
