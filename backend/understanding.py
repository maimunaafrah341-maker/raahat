"""Turn a free-text description ("machine lo vellu tegipoyayi") into the app's
injury key and situation tags, using Gemini structured output.

The result only PRE-FILLS the form; the user confirms before anything is searched.
Categories are constrained to the app's own lists, so Gemini can't invent one.
"""
import enum
import json

from google.genai import types
from pydantic import BaseModel

from backend import rag
from backend.triage import CONDITIONS, INJURIES

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


class Understanding(BaseModel):
    injury: InjuryKey
    situations: list[SituationKey]
    conditions: list[ConditionKey]
    life_threatening_signs: bool
    language: LanguageKey


_PROMPT = """Classify an emergency description written by someone in Hyderabad, India. It may be in English, \
Hindi, Telugu or Urdu, in native script or romanized (Latin letters), or mixed.

injury -- the emergency: pick exactly one key, or "unclear" if the text doesn't describe an emergency or fits none well:
{injuries}

conditions -- facts about the PATIENT that the text clearly states (empty list if none; never guess):
{conditions}

situations -- pick ONLY those the text clearly states (empty list if none; never guess):
{situations}

life_threatening_signs -- true only if the text mentions: unconscious / not responding, not breathing or \
struggling to breathe, very heavy bleeding that won't stop, seizure, severe chest pain, a large burn, stroke signs \
(face drooping, arm weakness, slurred speech), throat or tongue swelling, poison swallowed, a snake bite, \
heavy bleeding in pregnancy, or a baby that is floppy, blue or won't wake. Otherwise false.

language -- the language the text is written in.

Text:
{text}"""


def script_language(text: str) -> str | None:
    """Language implied by native script characters, if any (romanized text returns None)."""
    for lang, ranges in _NATIVE_RANGES.items():
        if any(lo <= ord(ch) <= hi for ch in text for lo, hi in ranges):
            return lang
    return None


def understand(text: str) -> dict | None:
    """Return {injury, situations, conditions, life_threatening_signs, language}, or None if Gemini is unavailable."""
    prompt = _PROMPT.format(
        injuries="\n".join(f"- {k}: {v['label']}" for k, v in INJURIES.items()),
        situations="\n".join(f"- {k}: {v['label']}" for k, v in rag.SITUATIONS.items()),
        conditions="\n".join(f"- {k}: {v['label']}" for k, v in CONDITIONS.items()),
        text=text,
    )
    config = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json", response_schema=Understanding)
    try:
        raw, _model = rag._generate_with(prompt, config)
        parsed = Understanding.model_validate(json.loads(raw))
    except (*rag.AI_ERRORS, ValueError):
        return None
    injury = parsed.injury.value
    return {
        "injury": None if injury == "unclear" else injury,
        "situations": list(dict.fromkeys(s.value for s in parsed.situations)),
        "conditions": list(dict.fromkeys(c.value for c in parsed.conditions)),
        "life_threatening_signs": parsed.life_threatening_signs,
        # A native script is certain; otherwise trust Gemini's reading of romanized text.
        "language": script_language(text) or parsed.language.value,
    }
