"""Read text aloud in any of the app's languages with Gemini text-to-speech.

Browsers only speak languages the phone has a voice for, and most phones and
laptops have no Telugu or Urdu voice. The app asks here instead, one short
chunk at a time so the first words play within a few seconds.
"""
import hashlib
import io
import os
import time
import wave
from collections import OrderedDict

from google.genai import types

from backend import rag

TTS_MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_TTS_MODELS", "gemini-3.8-flash-lite-tts,gemini-3.8-flash-tts,gemini-2.5-flash-preview-tts").split(",")
    if m.strip()]
VOICE = "Kore"          # a calm, clear voice that handles all four languages
MAX_CHARS = 600         # one chunk: a step or a short paragraph
BUDGET_S = 25
_SAMPLE_RATE = 24000    # what Gemini returns when it sends raw PCM

_cache: OrderedDict[str, bytes] = OrderedDict()
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


def speak(text: str, language: str) -> tuple[bytes, str]:
    """Return (wav bytes, model used). Raises one of rag.AI_ERRORS if no model answers in time."""
    key = hashlib.sha256(f"{language}\n{VOICE}\n{text}".encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key], "cache"
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
        audio = _as_wav(part.data)
        _cache[key] = audio
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
        return audio, model
    if isinstance(last_error, rag.AI_ERRORS):
        raise last_error
    raise rag.OutOfTime("no text-to-speech model answered")
