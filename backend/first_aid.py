"""Fixed, sourced first-aid steps per injury (corpus/first_aid_*.md).

The card shown in the app is the reviewed text itself, never generated. Gemini
only translates it, and a translation is used only if every number survives
and the step count matches; otherwise the English is shown.
"""
import re

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


def first_aid(injury_key: str, language: str = "en") -> dict | None:
    doc_id = rag.FIRST_AID_DOCS.get(injury_key)
    if not doc_id:
        return None
    if (injury_key, language) in _cache:
        return _cache[(injury_key, language)]
    card = _parse(doc_id)
    card.update(language="en", translated=False)
    if language in LANGUAGE_NAMES and language != "en":
        steps, cautions = _translate_list(card["steps"], language), _translate_list(card["cautions"], language)
        if steps is not None and cautions is not None:
            card.update(steps_en=card["steps"], cautions_en=card["cautions"], steps=steps, cautions=cautions,
                        language=language, translated=True)
    # Cache only final results, so a temporary translation failure is retried next time.
    if language == "en" or card["translated"]:
        _cache[(injury_key, language)] = card
    return card
