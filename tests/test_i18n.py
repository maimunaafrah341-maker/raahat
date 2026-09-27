"""UI translation coverage (pattern from Athena's tests/test_i18n.py)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))
sys.path.insert(0, str(ROOT))

from i18n import LANGUAGES, STRINGS  # noqa: E402

from backend.rag import SITUATIONS  # noqa: E402
from backend.triage import INJURIES  # noqa: E402

EN = STRINGS["en"]


def test_every_language_has_every_key():
    for lang in LANGUAGES:
        assert set(STRINGS[lang]) == set(EN), f"{lang}: key mismatch {set(STRINGS[lang]) ^ set(EN)}"


def test_no_value_left_in_english():
    for lang in LANGUAGES:
        if lang == "en":
            continue
        for key, value in STRINGS[lang].items():
            if EN[key]:
                assert value != EN[key], f"{lang}.{key} is untranslated"


def test_placeholders_match():
    for lang in LANGUAGES:
        for key, value in STRINGS[lang].items():
            assert set(re.findall(r"\{(\w+)\}", value)) == set(re.findall(r"\{(\w+)\}", EN[key])), f"{lang}.{key}"


def test_safety_numbers_kept():
    for lang in LANGUAGES:
        assert "108" in STRINGS[lang]["banner_108"], lang


def test_every_backend_injury_and_situation_has_a_label():
    for key in INJURIES:
        assert f"injury.{key}" in EN, key
    for key in SITUATIONS:
        assert f"situation.{key}" in EN, key
