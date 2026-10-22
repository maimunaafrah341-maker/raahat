"""Citations, verified dates, the low-confidence fallback, checklist sources and log scrubbing.

None of these call Gemini: the network-dependent parts are replaced with fakes.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import analytics, rag  # noqa: E402
from backend.checklist import BY_CONDITION, BY_INJURY, BY_SITUATION, ITEMS, checklist  # noqa: E402
from backend.triage import CONDITIONS, INJURIES  # noqa: E402


def test_every_corpus_document_has_a_verified_date():
    for doc_id in rag.DOC_TITLES:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rag.doc_verified(doc_id) or ""), doc_id


def test_verified_line_is_not_indexed_as_content():
    for path in rag.CORPUS_DIR.glob("*.md"):
        for chunk in rag.chunk_document(path):
            assert "Last verified" not in chunk["text"], chunk["id"]


def test_low_confidence_question_is_not_answered(monkeypatch):
    monkeypatch.setattr(rag, "ensure_index", lambda: None)
    monkeypatch.setattr(rag, "question_confidence", lambda q, exclude=(): 0.5)
    called = []
    monkeypatch.setattr(rag, "generate_explanation", lambda *a, **k: called.append(1))
    out = rag.explain("Deep cut", question="What is the parking fee?", injury_key="deep_cut")
    assert out["low_confidence"] and not out["generated"] and not called
    assert "108" in out["explanation"] and "not sure" in out["explanation"]


def test_confident_answer_carries_source_dates(monkeypatch):
    monkeypatch.setattr(rag, "ensure_index", lambda: None)
    monkeypatch.setattr(rag, "question_confidence", lambda q, exclude=(): 0.9)
    chunk = {"id": "x", "text": "t", "similarity": 0.9, "doc_score": 0.9,
             "metadata": {"doc_id": "clinical_establishments_act", "kind": "key_fact",
                          "title": rag.DOC_TITLES["clinical_establishments_act"], "citation": "c"}}
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: [chunk])
    monkeypatch.setattr(rag, "generate_explanation", lambda *a, **k: ("- answer [x]", "fake-model"))
    out = rag.explain("Deep cut", question="Can they ask me to pay first?", injury_key="deep_cut")
    assert not out["low_confidence"]
    assert out["sources"][0]["verified"] == rag.doc_verified("clinical_establishments_act")


def test_checklist_keys_are_known_and_sources_exist():
    for mapping in (BY_INJURY, BY_CONDITION, BY_SITUATION):
        for items in mapping.values():
            assert set(items) <= set(ITEMS)
    assert set(BY_INJURY) <= set(INJURIES) and set(BY_CONDITION) <= set(CONDITIONS)
    assert set(BY_SITUATION) <= set(rag.SITUATIONS)
    for key, item in ITEMS.items():
        assert item["source"] is None or item["source"] in rag.DOC_TITLES, key


def test_chemo_checklist_has_the_laborer_story_documents():
    c = checklist("chemo_fever", ["chemotherapy"])
    assert {"aadhaar", "referral", "chemo"} <= set(c["patient"])
    assert {"ration_card", "aarogyasri_card"} == set(c["scheme"])
    assert len(c["patient"]) == len(set(c["patient"]))


def test_localities_are_in_hyderabad_and_labelled():
    import json
    from backend.i18n import STRINGS
    locs = json.loads((ROOT / "data" / "localities.json").read_text(encoding="utf-8"))
    names = [l["name"] for l in locs]
    assert len(names) == len(set(names)) and "Charminar" in names  # the page's default start point
    for l in locs:
        assert 17.15 < l["lat"] < 17.65 and 78.2 < l["lng"] < 78.75, l["name"]
        assert f"zone.{l['zone']}" in STRINGS["en"], l["zone"]


def test_every_hospital_phone_is_sourced():
    import json
    data = json.loads((ROOT / "data" / "hospitals_real.json").read_text(encoding="utf-8"))
    for h in data["hospitals"]:
        if h.get("phone"):
            assert re.fullmatch(r"\+91\d{10}|1\d{3}", h["phone"]["number"]), h["name"]
            assert h["phone"]["source"]["url"].startswith("https://"), h["name"]


def test_gated_and_situation_documents_exist():
    for doc, gate in rag.GATED_DOCS.items():
        assert doc in rag.DOC_TITLES and gate <= set(rag.SITUATIONS)
    for s in rag.SITUATIONS.values():
        assert set(s["include"]) <= set(rag.DOC_TITLES)


def test_spoken_place_names_match_areas():
    from backend.understanding import match_area
    assert match_area("Kukatpalli") == "Kukatpally"
    assert match_area("kukat pally") == "Kukatpally"
    assert match_area("Dilsukh Nagar") == "Dilsukhnagar"
    assert match_area("L B Nagar") == "LB Nagar"
    assert match_area("Mumbai") is None and match_area("") is None


def test_any_wrong_link_opens_the_app():
    from backend.app import app
    client = app.test_client()
    for path in ("/hom", "/index", "/hospitals/osmania", "/api/admin/stats"):
        res = client.get(path)
        if path.startswith("/api/"):
            assert res.status_code == 404  # hidden admin pages stay hidden, as a short JSON answer
        else:
            assert res.status_code == 302 and res.headers["Location"].endswith("/"), path
    assert client.get("/").status_code == 200


def test_scrub_removes_numbers_and_emails():
    text = analytics.scrub("call me on 98480 22338 or a@b.com, aadhaar 1234 5678 9012, age 45")
    assert "98480" not in text and "a@b.com" not in text and "9012" not in text
    assert "age 45" in text  # short numbers (ages, temperatures) are kept for context


def test_coarse_area_is_about_a_kilometre():
    assert analytics.coarse_area(17.372954, 78.47427) == "17.37,78.47"
