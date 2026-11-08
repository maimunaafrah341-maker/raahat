"""iPhone/Safari recordings: recorded as one piece (sliced MP4 can't be decoded by Safari, "Decoding failed"),
and a recording the phone can't read shows a plain message in the person's language, never the raw error."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.i18n import STRINGS  # noqa: E402

APP_JS = (ROOT / "frontend" / "web" / "app.js").read_text(encoding="utf-8")
SCRIPT = {"hi": r"[ऀ-ॿ]", "te": r"[ఀ-౿]", "ur": r"[؀-ۿ]"}


def test_only_webm_recorders_record_in_slices():
    assert 'const RECORD_IN_SLICES = !!window.MediaRecorder?.isTypeSupported?.("audio/webm");' in APP_JS
    start = APP_JS[APP_JS.index("async function startRecording"):APP_JS.index("function stopRecording")]
    assert "if (RECORD_IN_SLICES) rec.mr.start(250);\n  else rec.mr.start();" in start
    assert start.count("rec.mr.start(") == 2


def test_unreadable_recording_message_in_all_four_languages():
    assert "Couldn't read that recording" in STRINGS["en"]["voice.unreadable"]
    for lang, script in SCRIPT.items():
        assert re.search(script, STRINGS[lang]["voice.unreadable"]), lang


def test_the_raw_decoding_error_is_never_shown():
    stopped = APP_JS[APP_JS.index("async function onRecordingStopped"):]
    stopped = stopped[:stopped.index("\n}\n")]
    assert 'err.name === "EncodingError"' in stopped and "/decod/i.test(" in stopped
    assert 't("voice.unreadable")' in stopped
