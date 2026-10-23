"""Fixed, sourced first-aid steps per injury (corpus/first_aid_*.md).

The card shown in the app is the reviewed text itself, never generated. Gemini
only translates it, and a translation is used only if every number survives
and the step count matches; otherwise the English is shown.
"""
import hashlib
import json
import re
from pathlib import Path

from backend import rag
from backend.translation import LANGUAGE_NAMES, translate_explanation


def _parse(doc_id: str) -> dict:
    text = (rag.CORPUS_DIR / f"{doc_id}.md").read_text(encoding="utf-8")
    sections, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^(Source|Key fact|Caveat):\s*(.*)$", line)
        if m:
            current = m.group(1)
            sections[current] = {"intro": m.group(2), "items": []}
        elif line.startswith("- ") and current:
            sections[current]["items"].append(line[2:].strip())
    return {
        "doc_id": doc_id,
        "title": rag.DOC_TITLES[doc_id],
        "steps": sections["Key fact"]["items"],
        "cautions": sections["Caveat"]["items"],
        "citation": sections["Source"]["intro"],
        "verified": rag.doc_verified(doc_id),
    }


def _translate_list(items: list[str], language: str) -> list[str] | None:
    if not items:
        return items
    translated = translate_explanation("\n".join(f"* {i}" for i in items), language)
    if not translated:
        return None
    out = [line[2:].strip() for line in translated.splitlines() if line.startswith(("* ", "- "))]
    return out if len(out) == len(items) else None


_cache: dict[tuple[str, str], dict] = {}
# Translations made ahead of time by data/translate_cards.py, so cards appear instantly in every
# language and still do when Gemini is busy. Live translation is only the fallback.
SAVED_FILE = Path(__file__).resolve().parent.parent / "data" / "card_translations.json"
_saved: dict | None = None


def source_hash(card: dict) -> str:
    """Fingerprint of the English a translation was made from; an edited card no longer matches."""
    return hashlib.sha256(json.dumps([card["steps"], card["cautions"]], ensure_ascii=False).encode()).hexdigest()[:16]


def load_saved() -> dict:
    global _saved
    if _saved is None:
        _saved = json.loads(SAVED_FILE.read_text(encoding="utf-8")) if SAVED_FILE.exists() else {}
    return _saved


def _saved_translation(card: dict, language: str) -> tuple[list[str], list[str]] | None:
    entry = load_saved().get(f"{card['doc_id']}/{language}")
    if (entry and entry.get("source") == source_hash(card)
            and len(entry["steps"]) == len(card["steps"]) and len(entry["cautions"]) == len(card["cautions"])):
        return entry["steps"], entry["cautions"]
    return None


def first_aid(injury_key: str, language: str = "en") -> dict | None:
    doc_id = rag.FIRST_AID_DOCS.get(injury_key)
    return card_for(doc_id, language) if doc_id else None


def danger_signs(condition: str, language: str = "en") -> dict | None:
    doc_id = rag.CONDITION_DOCS.get(condition)
    return card_for(doc_id, language) if doc_id else None


def card_for(doc_id: str, language: str = "en") -> dict:
    if (doc_id, language) in _cache:
        return _cache[(doc_id, language)]
    card = _parse(doc_id)
    # "danger" cards list warning signs to act on; "first_aid" cards list steps to take;
    # "crisis" is the mental health card, shown with its helplines as call buttons.
    kind = "danger" if doc_id.startswith("danger_") else "crisis" if doc_id.startswith("crisis_") else "first_aid"
    card.update(kind=kind, language="en", translated=False)
    if language in LANGUAGE_NAMES and language != "en":
        saved = _saved_translation(card, language)
        if saved:
            steps, cautions = saved
        else:
            steps = _translate_list(card["steps"], language)
            cautions = _translate_list(card["cautions"], language) if steps is not None else None
        if steps is not None and cautions is not None:
            card.update(steps_en=card["steps"], cautions_en=card["cautions"], steps=steps, cautions=cautions,
                        language=language, translated=True)
    # Cache only final results, so a temporary translation failure is retried next time.
    if language == "en" or card["translated"]:
        _cache[(doc_id, language)] = card
    return card
