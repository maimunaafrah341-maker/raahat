"""Turn a description -- typed, or spoken as audio -- into the app's injury key, situation
tags, patient conditions and area, using Gemini structured output.

The result fills the form; the person sees "what we understood" and can change any of it.
Categories and areas are constrained to the app's own lists, so Gemini can't invent one.
Spoken descriptions go to Gemini as audio, which copes with Telugu, Hindi, Urdu, English
and mixes of them far better than the browser's speech recognition.
"""
import difflib
import enum
import json
import os
import re
from pathlib import Path

from google.genai import types
from pydantic import BaseModel

from backend import rag
from backend.triage import CONDITIONS, INJURIES

_LOCALITIES = [l["name"] for l in json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "localities.json").read_text(encoding="utf-8"))]

# Someone in an emergency is waiting on this call, so it uses fast "lite" models first and moves on
# at the first error (no retries on the same model). Timed on a Telugu voice clip: 3.1-flash-lite
# answered correctly in ~6 s, while the main explanation model was rate-limited and took 30 s+.
UNDERSTAND_MODELS = [m for m in os.getenv("GEMINI_UNDERSTAND_MODELS", "").split(",") if m] or [
    "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview", rag.GEN_MODEL]

# Native-script ranges from Athena's understanding.detect_script().
_NATIVE_RANGES = {
    "hi": [(0x0900, 0x097F)],
    "te": [(0x0C00, 0x0C7F)],
    "ur": [(0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
}

InjuryKey = enum.Enum("InjuryKey", {k: k for k in [*INJURIES, "unclear"]}, type=str)
ConditionKey = enum.Enum("ConditionKey", {k: k for k in CONDITIONS}, type=str)
SituationKey = enum.Enum("SituationKey", {k: k for k in rag.SITUATIONS}, type=str)
LanguageKey = enum.Enum("LanguageKey", {k: k for k in ["en", "hi", "te", "ur", "other"]}, type=str)
AreaKey = enum.Enum("AreaKey", {f"a{i}": n for i, n in enumerate([*_LOCALITIES, "none"])}, type=str)


class Understanding(BaseModel):
    injury: InjuryKey
    situations: list[SituationKey]
    conditions: list[ConditionKey]
    life_threatening_signs: bool
    area: AreaKey
    place_said: str
    summary: str
    language: LanguageKey


class HeardUnderstanding(Understanding):
    transcript: str


_PROMPT = """Classify an emergency description from someone in Hyderabad, India. It may be in English, \
Hindi, Telugu or Urdu, in native script or romanized (Latin letters), or a mix (e.g. Telugu with English words). \
The person may be panicking: sentences may be broken, repeated or out of order.

injury -- the emergency: pick exactly one key, or "unclear" if it doesn't describe an emergency or fits none well:
{injuries}
(A bone that is or may be broken anywhere -- including the arm or hand, e.g. "చేయి విరిగింది", "हाथ टूट गया" -- is \
fracture; hand_finger is for cuts, crushing or a cut-off part of the hand or fingers.)

conditions -- facts about the PATIENT that are clearly stated (empty list if none; never guess):
{conditions}
(young_child only for a baby, infant, toddler or a stated age under 5 -- "my son" or "my daughter" alone is not enough.)

situations -- pick ONLY those clearly stated (empty list if none; never guess):
{situations}

life_threatening_signs -- true only if it mentions: unconscious / not responding, not breathing or struggling to \
breathe, choking, very heavy bleeding that won't stop, seizure, severe chest pain, a large burn, stroke signs \
(face drooping, arm weakness, slurred speech), throat or tongue swelling, poison or too many tablets swallowed, a \
snake bite, heavy bleeding in pregnancy, a baby that is floppy, blue or won't wake, or someone who has harmed \
themselves, is talking about killing themselves, or has a plan to. Otherwise false.

area -- where the patient is, ONLY if a place in this list is named (allow other spellings, e.g. "kukatpalli", \
"ఎల్బీ నగర్", "दिलसुखनगर", "కూకట్‌పల్లి" = Kukatpally); "none" if no place is named or it isn't in the list:
{areas}

place_said -- the place they named, written in English letters as it sounds (e.g. "Kukatpalli"); empty if none.

summary -- one short sentence, in the SAME language and script the person used, restating what happened, to whom \
and where, so they can check it was understood. Only what they said: no advice, no diagnosis, no reassurance.

language -- the language used.
{extra}
{source}"""

_TEXT_SOURCE = "Text:\n{text}"
_AUDIO_SOURCE = "The description is the attached audio recording."
_TRANSCRIPT_RULE = ("\ntranscript -- exactly what was said, in the script normally used for that language "
                    "(Telugu script for Telugu, etc.; keep English words as spoken). Empty if nothing was said.")


def script_language(text: str) -> str | None:
    """Language implied by native script characters, if any (romanized text returns None)."""
    for lang, ranges in _NATIVE_RANGES.items():
        if any(lo <= ord(ch) <= hi for ch in text for lo, hi in ranges):
            return lang
    return None


def _prompt(source: str, extra: str = "") -> str:
    return _PROMPT.format(
        injuries="\n".join(f"- {k}: {v['label']}" for k, v in INJURIES.items()),
        situations="\n".join(f"- {k}: {v['label']}" for k, v in rag.SITUATIONS.items()),
        conditions="\n".join(f"- {k}: {v['label']}" for k, v in CONDITIONS.items()),
        areas=", ".join(_LOCALITIES),
        extra=extra, source=source,
    )


def _norm_place(s: str) -> str:
    """Spelling-tolerant key: 'Kukatpalli', 'kukat pally', 'Kukatpally' -> the same string."""
    s = re.sub(r"[^a-z]", "", s.lower())
    for a, b in (("pally", "palli"), ("palle", "palli"), ("gooda", "guda"), ("gudda", "guda"),
                 ("puram", "puram"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("th", "t"), ("dh", "d"), ("bh", "b")):
        s = s.replace(a, b)
    return s


_NORMED = {_norm_place(n): n for n in _LOCALITIES}


def match_area(place: str) -> str | None:
    """Best locality for a place name as spoken, or None if nothing is close enough."""
    key = _norm_place(place or "")
    if len(key) < 3:
        return None
    if key in _NORMED:
        return _NORMED[key]
    close = difflib.get_close_matches(key, list(_NORMED), n=1, cutoff=0.82)
    return _NORMED[close[0]] if close else None


def _result(parsed: Understanding, text: str) -> dict:
    injury = parsed.injury.value
    area = parsed.area.value
    if area == "none":
        area = match_area(parsed.place_said) or "none"
    return {
        "injury": None if injury == "unclear" else injury,
        "situations": list(dict.fromkeys(s.value for s in parsed.situations)),
        "conditions": list(dict.fromkeys(c.value for c in parsed.conditions)),
        "life_threatening_signs": parsed.life_threatening_signs,
        "area": None if area == "none" else area,
        "summary": parsed.summary.strip()[:300],
        # A native script is certain; otherwise trust Gemini's reading of romanized text.
        "language": script_language(text) or parsed.language.value,
    }


def understand(text: str) -> dict | None:
    """Return {injury, situations, conditions, life_threatening_signs, area, summary, language}, or None
    if Gemini is unavailable."""
    config = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json", response_schema=Understanding)
    try:
        raw, model = rag._generate_with(_prompt(_TEXT_SOURCE.format(text=text)), config, UNDERSTAND_MODELS, attempts=1)
        parsed = Understanding.model_validate(json.loads(raw))
    except (*rag.AI_ERRORS, ValueError):
        return None
    return {**_result(parsed, text), "model": model}


def understand_audio(audio: bytes, mime_type: str, language_hint: str | None = None) -> dict | None:
    """Same as understand(), from a voice recording; also returns what was heard as `transcript`."""
    hint = (f"\nThe app is set to {language_hint}, but they may speak any of the four languages or mix them."
            if language_hint else "")
    config = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json", response_schema=HeardUnderstanding)
    contents = [types.Part.from_bytes(data=audio, mime_type=mime_type),
                _prompt(_AUDIO_SOURCE, _TRANSCRIPT_RULE + hint)]
    try:
        raw, model = rag._generate_with(contents, config, UNDERSTAND_MODELS, attempts=1)
        parsed = HeardUnderstanding.model_validate(json.loads(raw))
    except (*rag.AI_ERRORS, ValueError):
        return None
    transcript = parsed.transcript.strip()[:1000]
    if not transcript:
        return {"transcript": "", "injury": None, "situations": [], "conditions": [], "area": None,
                "life_threatening_signs": False, "summary": "", "language": None}
    return {**_result(parsed, transcript), "transcript": transcript, "model": model}
