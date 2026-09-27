"""Translate a checked English entitlement explanation into the user's language.

Adapted from Athena's translation.translate_reply(). The English text stays
authoritative: guardrails (no guarantees, valid citations) run on the English
before it gets here, and the UI always offers the English original next to
the translation, labelled as machine translation.
"""
import re

from google.genai import types

from backend import rag

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "te": "Telugu", "ur": "Urdu"}

_PROMPT = """You are translating information for a person who speaks {language} and may not read fluently.

Rules:
- Translate into {language}, in the script normally used for that language.
- Translate ONLY what is written. Add no reassurance, advice, greeting, closing, or detail that is not already there.
- Keep every "may", "might" and "if" -- these are possibilities, not promises, and must stay that way.
- Keep plain, warm, everyday words; avoid formal or legal register.
- Keep all numbers and amounts exactly as written, in Western digits (e.g. ₹5,00,000, 90+, 18–60).
{citation_rule}- Keep the bullet list structure (lines starting with "* ").
- Output the translation and nothing else.

Text:
{text}"""

_CITATION_RX = re.compile(r"\[[^\]]+\]")
_NUMBER_RX = re.compile(r"\d[\d,]*")


def _preserved(original: str, translated: str) -> bool:
    """Citations and every number/amount must survive translation unchanged."""
    if sorted(_CITATION_RX.findall(original)) != sorted(_CITATION_RX.findall(translated)):
        return False
    return set(_NUMBER_RX.findall(original)) <= set(_NUMBER_RX.findall(translated))


def translate_explanation(text: str, language: str) -> str | None:
    """Return the translation, or None when there's nothing to do or it can't be trusted.

    None means "no translation available": callers show the English alone rather
    than an unchecked translation.
    """
    if not text or language not in LANGUAGE_NAMES or language == "en":
        return None
    # Only mention citations when there are some: without any, smaller models start bracketing sentences.
    citation_rule = ("- Keep every text inside square brackets [like this] EXACTLY as written, in English -- "
                     "these are source citations.\n") if _CITATION_RX.search(text) else ""
    prompt = _PROMPT.format(language=LANGUAGE_NAMES[language], text=text, citation_rule=citation_rule)
    for _ in range(2):
        try:
            resp, _model = rag._generate_with(
                prompt, types.GenerateContentConfig(temperature=0.1))
        except rag.AI_ERRORS:
            return None
        translated = (resp or "").strip()
        if translated and _preserved(text, translated):
            return translated
    return None
