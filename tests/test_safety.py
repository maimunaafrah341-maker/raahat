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


def test_slow_models_never_outlast_the_time_budget(monkeypatch):
    """Ten overloaded models that each take 1 s must not keep a person waiting past the budget."""
    import time as _time

    import requests

    class Slow:
        class models:  # noqa: N801 -- mimics client.models
            @staticmethod
            def generate_content(**_):
                _time.sleep(1)
                raise requests.exceptions.ConnectionError("overloaded")

    monkeypatch.setattr(rag, "client", lambda timeout_ms=0: Slow)
    started = _time.monotonic()
    try:
        rag._generate_with("hi", None, models=[f"m{i}" for i in range(10)], attempts=1, budget_s=5)
    except rag.AI_ERRORS:
        pass
    assert _time.monotonic() - started < 5.5  # stopped by the budget, not after all ten


def test_research_spreadsheet_import(tmp_path, monkeypatch, capsys):
    import json
    import shutil
    sys.path.insert(0, str(ROOT / "data"))
    import import_research as ir
    real = tmp_path / "hospitals_real.json"
    shutil.copy(ROOT / "data" / "hospitals_real.json", real)
    monkeypatch.setattr(ir, "REAL_FILE", real)
    before = len(json.loads(real.read_text(encoding="utf-8"))["hospitals"])
    csv_file = tmp_path / "research.csv"
    header = (ROOT / "data" / "research_template.csv").read_text(encoding="utf-8").splitlines()[0]
    csv_file.write_text("\n".join([
        header,
        "Test Care Hospital,Kukatpally,17.49,78.40,private,yes,2,emergency_medicine;orthopedics,unknown,,"
        "040 1234 5678,emergency,https://test.example/contact,Website: 24x7 casualty|https://test.example,2026-10-25,yes",
        "Bad Specialty Hospital,Ameerpet,17.43,78.44,private,yes,2,brain_magic,unknown,,,,,Site|https://x.example,,no",
        "No Source Hospital,Ameerpet,17.43,78.44,private,yes,2,,unknown,,,,,,,no",
    ]), encoding="utf-8")
    assert ir.main(str(csv_file)) == 0
    out = capsys.readouterr().out
    assert "unknown specialties" in out and "needs at least one source" in out
    data = json.loads(real.read_text(encoding="utf-8"))
    added = next(h for h in data["hospitals"] if h["name"] == "Test Care Hospital")
    assert len(data["hospitals"]) == before + 1
    assert added["phone"]["number"] == "+914012345678" and added["data_level"] == "phone_verified"
    ir.validate_real(data)


def test_unchecked_hospitals_rank_after_researched_and_say_call_first():
    from backend.triage import rank_facilities
    researched = {"id": 1, "name": "R", "lat": 17.40, "lng": 78.48, "specialties": ["orthopedics", "emergency_medicine"],
                  "trauma_level": 2, "trauma_label": "intermediate", "emergency_24x7": True, "data_level": "public"}
    unchecked = [{"id": 10 + i, "name": f"U{i}", "lat": 17.3616, "lng": 78.4747 + i * 0.001, "specialties": [],
                  "trauma_level": 0, "trauma_label": "none", "emergency_24x7": None, "data_level": "unchecked"}
                 for i in range(15)]
    ranked = rank_facilities([*unchecked, researched], "fracture", 17.3616, 78.4747)
    assert ranked[0]["name"] == "R"  # the researched hospital first, though 4 km further
    rest = ranked[1:]
    assert len(rest) == 10 and all(r["tier"] == "unchecked" for r in rest)  # nearest 10 only
    assert all("call before going" in r["reasons"][0] for r in rest)  # never "not equipped"


def test_hospital_list_is_gzipped_for_phones():
    import gzip
    import json
    from backend.app import app
    res = app.test_client().get("/api/facilities", headers={"Accept-Encoding": "gzip"})
    assert res.headers.get("Content-Encoding") == "gzip"
    assert len(json.loads(gzip.decompress(res.data))) > 19


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
