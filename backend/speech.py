"""Read text aloud in any of the app's languages: Gnani Timbre for Telugu, Hindi and English, Gemini for Urdu
and whenever Gnani fails.

Browsers only speak languages the phone has a voice for, and most phones and
laptops have no Telugu or Urdu voice. The app asks here instead, one short
chunk at a time so the first words play within a few seconds.
"""
import hashlib
import io
import logging
import os
import time
import wave
from collections import OrderedDict

from google.genai import types

from backend import gnani, rag

log = logging.getLogger(__name__)

TTS_MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_TTS_MODELS", "gemini-3.8-flash-lite-tts,gemini-3.8-flash-tts,gemini-2.5-flash-preview-tts").split(",")
    if m.strip()]
VOICE = "Kore"          # a calm, clear voice that handles all four languages
MAX_CHARS = 600         # one chunk: a step or a short paragraph
BUDGET_S = 25
_SAMPLE_RATE = 24000    # what Gemini returns when it sends raw PCM

_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()  # -> (audio, model)
_CACHE_MAX = 400        # first-aid cards repeat, so most chunks are served from here


def _as_wav(data: bytes) -> bytes:
    """Newer models send a WAV file; older ones send raw 16-bit PCM, which browsers can't play."""
    if data[:4] == b"RIFF":
        return data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(data)
    return buf.getvalue()


def provider(model: str) -> str:
    """Who made the audio, for the "Voice by Gnani" label: "gnani" or "gemini"."""
    return "gnani" if model.startswith("timbre") else "gemini"


def _remember(key: str, audio: bytes, model: str) -> None:
    _cache[key] = (audio, model)
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def speak(text: str, language: str, client: str | None = None) -> tuple[bytes, str]:
    """Return (wav bytes, model used). Raises one of rag.AI_ERRORS if no model answers in time.
    `client` (the visitor's IP) counts toward Gnani's call caps; a repeat served from the cache doesn't."""
    key = hashlib.sha256(f"{language}\n{text}".encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if gnani.supports(language) and gnani.take_quota(client):
        try:
            audio = gnani.synthesize(text, language)
        except gnani.GnaniError as err:
            log.warning("Gnani text to speech failed, falling back to Gemini: %s", err)
        else:
            _remember(key, audio, gnani.TTS_MODEL)
            return audio, gnani.TTS_MODEL
    audio, model = _gemini_speak(text)
    _remember(key, audio, model)
    return audio, model


def _gemini_speak(text: str) -> tuple[bytes, str]:
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))))
    start, last_error = time.monotonic(), None
    for model in TTS_MODELS:
        if time.monotonic() - start > BUDGET_S:
            break
        try:
            resp = rag.client(20000).models.generate_content(model=model, contents=text, config=config)
            part = resp.candidates[0].content.parts[0].inline_data
        except rag.AI_ERRORS as e:
            last_error = e
            continue
        except (AttributeError, IndexError, TypeError) as e:  # answered without audio
            last_error = e
            continue
        if not part or not part.data:
            continue
        return _as_wav(part.data), model
    if isinstance(last_error, rag.AI_ERRORS):
        raise last_error
    raise rag.OutOfTime("no text-to-speech model answered")
