"""Sources are shown once under an answer: as chips inside the answer (with the checked date on tap),
never repeated as a separate "From:" list. Read aloud still skips them."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.i18n import STRINGS  # noqa: E402

APP_JS = (ROOT / "frontend" / "web" / "app.js").read_text(encoding="utf-8")


def _answer():
    return APP_JS[APP_JS.index("function renderAnswer"):APP_JS.index("function renderChat")]


def test_no_separate_from_list():
    assert "function sourceLine" not in APP_JS and 'class="from"' not in APP_JS
    assert "sourceLine(" not in _answer()
    for lang in ("en", "hi", "te", "ur"):
        assert "answer.from" not in STRINGS[lang]


def test_chips_carry_the_checked_date_in_all_four_languages():
    chip = APP_JS[APP_JS.index("function citeChip"):APP_JS.index("const countCites")]
    assert 't("answer.verified"' in chip and "fmtDate(s.verified)" in chip
    assert 'class="cite__date" hidden' in chip and 'aria-expanded="false"' in chip  # one line until tapped
    for lang in ("en", "hi", "te", "ur"):
        assert "{date}" in STRINGS[lang]["answer.verified"], lang


def test_answer_text_chips_use_the_answers_sources():
    assert "renderExplanation(translated || m.content, m.sources || [])" in _answer()
    assert re.search(r"withCites = .*citeChip\(c, sources\)", APP_JS)


def test_sources_only_follow_the_answer_when_its_text_kept_none():
    a = _answer()
    assert "m.generated && !countCites(body) && m.sources?.length" in a  # not for the fixed fallback text
    # Dated chips are class="cite cite--dated": they must count, or every answer gets a second row of sources.
    assert '/class="cite[ "]/g' in APP_JS[APP_JS.index("const countCites"):][:120]


def test_read_aloud_is_unchanged_and_skips_the_chips():
    a = _answer()
    assert 'speakButton(".msg--ai")' in a
    assert a.index("speakButton(") > a.index('class="explanation"')
    speakable = APP_JS[APP_JS.index("function speakableText"):]
    assert ".cite" in speakable[:400] and "button" in speakable[:400]
