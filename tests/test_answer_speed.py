"""The answer to a question must come quickly or fall back quickly, in the person's language. Gemini is faked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import rag, translation  # noqa: E402
from backend.i18n import STRINGS  # noqa: E402

CHUNK = {"id": "c1", "similarity": 0.8, "doc_score": 0.8, "text": "Aarogyasri covers fractures.",
         "metadata": {"doc_id": "telangana_aarogyasri", "title": "Telangana Rajiv Aarogyasri Scheme", "kind": "key_fact",
                      "citation": "x"}}


def test_answer_uses_fast_models_once_each_within_the_budget(monkeypatch):
    calls = []

    def fake_generate_with(prompt, config, models=None, attempts=2, timeout_ms=0, budget_s=0):
        calls.append((models, attempts, timeout_ms, budget_s))
        return "A fine answer [Telangana Rajiv Aarogyasri Scheme].", models[0]

    monkeypatch.setattr(rag, "_generate_with", fake_generate_with)
    text, model = rag.generate_explanation("Fracture", None, None, [CHUNK], "Is it free?")
    models, attempts, timeout_ms, budget_s = calls[0]
    assert models == rag.ANSWER_MODELS and attempts == 1 and timeout_ms == rag.ANSWER_TIMEOUT_MS
    assert budget_s <= rag.ANSWER_BUDGET_S and model == rag.ANSWER_MODELS[0]


def test_no_time_for_the_rewrite_keeps_the_first_draft(monkeypatch):
    drafts = iter(["You will definitely get it free.", rag.OutOfTime("budget used up")])  # a promise: rewrite asked

    def fake_generate(prompt, budget_s):
        d = next(drafts)
        if isinstance(d, Exception):
            raise d
        return d, "lite"

    monkeypatch.setattr(rag, "_generate", fake_generate)
    text, model = rag.generate_explanation("Fracture", None, None, [CHUNK], "Is it free?")
    assert text.startswith("You will definitely get it free.") and "not guarantees" in text


def test_no_answer_in_time_raises_so_the_fallback_shows(monkeypatch):
    def slow(prompt, budget_s):
        raise rag.OutOfTime("Gemini did not answer within the time budget")
    monkeypatch.setattr(rag, "_generate", slow)
    try:
        rag.generate_explanation("Fracture", None, None, [CHUNK], "Is it free?")
    except rag.AI_ERRORS:
        return
    raise AssertionError("expected the time-out to reach explain()")


def test_fallback_message_is_in_the_persons_language(monkeypatch):
    from backend import app as app_module
    monkeypatch.setattr(app_module.rag, "explain", lambda *a, **k: {
        "explanation": rag.fallback_explanation([{"title": "Telangana Rajiv Aarogyasri Scheme"}]),
        "generated": False, "low_confidence": False, "confidence": 0.74,
        "sources": [{"doc_id": "telangana_aarogyasri", "title": "Telangana Rajiv Aarogyasri Scheme"}],
        "model": {"generation": None}})
    client = app_module.app.test_client()
    for lang in ("te", "hi", "ur", "en"):
        res = client.post("/api/entitlements", json={"injury": "fracture", "question": "free?", "language": lang}).get_json()
        assert res["explanation"].startswith(STRINGS[lang]["answer.fallback"]), lang
        assert "- Telangana Rajiv Aarogyasri Scheme" in res["explanation"]
        assert res["explanation_translated"] is None


def test_answer_translation_is_fast_but_card_translation_is_unchanged(monkeypatch):
    calls = []

    def fake_generate_with(prompt, config, models=None, attempts=2, timeout_ms=0, budget_s=0):
        calls.append((models, budget_s))
        return "అనువాదం 108", "m"

    monkeypatch.setattr(rag, "_generate_with", fake_generate_with)
    assert translation.translate_explanation("Call 108", "te", fast=True) == "అనువాదం 108"
    assert calls[-1][0] == rag.ANSWER_MODELS and calls[-1][1] <= translation.TRANSLATE_FAST_BUDGET_S
    translation.translate_explanation("Call 108", "te")
    assert calls[-1] == (None, 25)  # first-aid cards keep the old, patient chain
