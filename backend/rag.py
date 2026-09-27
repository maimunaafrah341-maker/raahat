"""Entitlement RAG: chunk the corpus, embed with Gemini, store in Chroma, explain with Gemini.

Build/rebuild the index:  python -m backend.rag build
Try a query:              python -m backend.rag ask hand_finger 10
"""
import os
import re
import sys
import time
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CORPUS_DIR = ROOT / "corpus"
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION = "entitlements"
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEN_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# Tried in order when the primary model is overloaded (503) or rate-limited (429).
GEN_FALLBACK_MODELS = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-flash-lite-latest"]

# Documents whose best chunk is within this cosine similarity of the top document are kept.
# Tuned on sample situations: 0.04 keeps 1-3 of the 4 documents.
RELEVANCE_MARGIN = 0.04
MAX_DOCS = 3

# Short human-readable names used for citations in the generated text.
DOC_TITLES = {
    "clinical_establishments_act": "Clinical Establishments Act, 2010 (Telangana Rules, 2011)",
    "paschim_banga_case": "Paschim Banga Khet Mazdoor Samity v. State of West Bengal (1996)",
    "telangana_aarogyasri": "Telangana Rajiv Aarogyasri Scheme",
    "telangana_bocw": "Telangana BOCW Welfare Board (BOCW Act, 1996)",
}

# Each corpus file is a sequence of labelled sections. The label decides the chunk kind.
SECTION_LABELS = [
    (re.compile(r"^Source:"), "source"),
    (re.compile(r"^Key fact:"), "key_fact"),
    (re.compile(r"^Caveat"), "caveat"),
    (re.compile(r"^Use this"), "usage_guidance"),
]

_client = None
_RETRYABLE = (429, 500, 503)


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _with_retry(fn, attempts: int = 3):
    for i in range(attempts):
        try:
            return fn()
        except genai_errors.APIError as e:
            if e.code not in _RETRYABLE or i == attempts - 1:
                raise
            time.sleep(1.5 * (i + 1))


# ---------- chunking ----------

def chunk_document(path: Path) -> list[dict]:
    """Split one corpus file into its labelled sections (source / key fact / caveat / guidance)."""
    doc_id = path.stem
    sections, kind, buf = [], None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        label = next((k for rx, k in SECTION_LABELS if rx.match(line)), None)
        if label:
            if buf:
                sections.append((kind, buf))
            kind, buf = label, [line]
        elif line.strip():
            buf.append(line)
    if buf:
        sections.append((kind, buf))

    citation = next((" ".join(b) for k, b in sections if k == "source"), "")
    citation = re.sub(r"\s+", " ", citation.removeprefix("Source:")).strip()
    chunks = []
    for i, (k, lines) in enumerate(sections):
        if k == "source":
            continue  # carried as metadata on every chunk instead
        text = re.sub(r"\s+", " ", " ".join(lines)).strip()
        chunks.append({
            "id": f"{doc_id}::{k}::{i}",
            # Title prefix so each chunk embeds with its document's context.
            "text": f"[{DOC_TITLES[doc_id]}] {text}",
            "metadata": {"doc_id": doc_id, "kind": k, "title": DOC_TITLES[doc_id], "citation": citation},
        })
    return chunks


def load_chunks() -> list[dict]:
    return [c for p in sorted(CORPUS_DIR.glob("*.md")) for c in chunk_document(p)]


# ---------- embeddings + store ----------

def embed(texts: list[str], task_type: str) -> list[list[float]]:
    res = _with_retry(lambda: client().models.embed_content(
        model=EMBED_MODEL, contents=texts, config=types.EmbedContentConfig(task_type=task_type)))
    return [e.values for e in res.embeddings]


def collection():
    store = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return store.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def build_index() -> int:
    chunks = load_chunks()
    col = collection()
    existing = col.get()["ids"]
    if existing:
        col.delete(ids=existing)
    col.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
        embeddings=embed([c["text"] for c in chunks], "RETRIEVAL_DOCUMENT"),
    )
    return len(chunks)


def ensure_index() -> None:
    if collection().count() == 0:
        build_index()


def retrieve(query: str, must_include: tuple[str, ...] = (), exclude: tuple[str, ...] = (),
             max_docs: int = MAX_DOCS, margin: float = RELEVANCE_MARGIN) -> list[dict]:
    """Score every chunk, rank documents by their best chunk, keep documents within
    `margin` of the top one (max `max_docs`), and return all chunks of those documents.

    Returning a selected document's caveat alongside its key fact means a benefit
    never reaches the generator without its limits. `must_include` forces documents
    in regardless of score (rule-based warnings, user-declared situations); `exclude`
    removes documents the user's declared situation rules out.
    """
    col = collection()
    res = col.query(query_embeddings=embed([query], "RETRIEVAL_QUERY"), n_results=col.count())
    hits = [
        {"id": i, "text": d, "metadata": m, "similarity": round(1 - dist, 3)}
        for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
        if m["doc_id"] not in exclude
    ]
    doc_score = {}
    for h in hits:  # hits are sorted best-first, so first sighting is the doc's best chunk
        doc_score.setdefault(h["metadata"]["doc_id"], h["similarity"])
    best = max(doc_score.values())
    keep = [d for d, s in doc_score.items() if s >= best - margin][:max_docs]
    keep += [d for d in must_include if d not in keep]
    return [{**h, "doc_score": doc_score[h["metadata"]["doc_id"]]}
            for h in hits if h["metadata"]["doc_id"] in keep]


# ---------- generation ----------

SYSTEM_PROMPT = """You explain patients' possible rights and financial support after a medical emergency \
in Telangana, India, to people under stress with limited literacy in legal language.

Hard rules:
- Use ONLY facts in the CONTEXT. Do not add any law, scheme, amount, phone number or procedure that is not in it.
- Never guarantee anything. Use "you may be eligible for…", "you may be able to…", and always say how to confirm.
  Never write "you have the right to" -- describe what the law requires of hospitals instead.
- A bullet may only cite the source its facts come from; never attribute one source's facts to another.
- For every source you use, keep EVERY point of its CAVEAT (e.g. registration or empanelment requirements, stabilization-only limits, and any "you can still register for the future" advice).
- Every bullet must end with its source in square brackets, using the document title given in the CONTEXT.
- CONTEXT sections marked GUIDANCE tell you how to use a source; follow them but do not quote them.
- If a source clearly doesn't apply to this person's situation, leave it out.
- Plain, warm, simple English. 4-7 short bullets, under 200 words total. No headings, no preamble, no legal advice disclaimer (the app shows one)."""


# Situations the user can tick. `phrase` feeds retrieval and the generator; `include` forces
# documents that are always relevant to that situation.
SITUATIONS = {
    "construction_worker": {
        "label": "Construction / building worker",
        "phrase": "I am a construction worker injured in building work",
        "include": ["telangana_bocw"],
    },
    "informal_worker": {
        "label": "Daily wage / informal labourer",
        "phrase": "I am an informal daily wage labourer",
        "include": [],
    },
    "bpl_card": {
        "label": "Have a BPL ration card / Aarogyasri enrolment",
        "phrase": "My family has a BPL ration card",
        "include": ["telangana_aarogyasri"],
    },
    "turned_away": {
        "label": "Was turned away or told to wait by a hospital",
        "phrase": "A hospital turned me away or told me to wait instead of treating my emergency",
        "include": ["clinical_establishments_act", "paschim_banga_case"],
    },
    "asked_to_pay_first": {
        "label": "Asked to pay before emergency treatment",
        "phrase": "The hospital asked me to pay before giving emergency treatment",
        "include": ["clinical_establishments_act"],
    },
}

# Documents that only apply to people in certain situations. When the user has ticked
# situations and none of these open the gate, the document is left out entirely.
GATED_DOCS = {"telangana_bocw": {"construction_worker", "informal_worker"}}


def situation_rules(tags: list[str]) -> tuple[list[str], tuple[str, ...], tuple[str, ...]]:
    """Return (phrases, must_include, exclude) for the ticked situation tags."""
    phrases = [SITUATIONS[t]["phrase"] for t in tags]
    must = tuple(dict.fromkeys(d for t in tags for d in SITUATIONS[t]["include"]))
    exclude = tuple(d for d, gate in GATED_DOCS.items() if tags and not gate & set(tags))
    return phrases, must, exclude


def build_situation_query(injury_label: str, facility: dict | None, situation: str | None) -> str:
    # The user's own words go first so they dominate the embedding over the fixed template.
    parts = [f"{situation}." if situation else "",
             f"Medical emergency: {injury_label}. My rights to emergency treatment and any help with costs."]
    if facility:
        emp = "is Aarogyasri-empanelled" if facility["aarogyasri_empanelled"] else "is NOT Aarogyasri-empanelled"
        parts.append(f"Hospital: {facility['type'].replace('_', ' ')}, {emp}.")
    return " ".join(p for p in parts if p)


def format_context(chunks: list[dict]) -> str:
    lines = []
    for c in chunks:
        kind = {"key_fact": "FACT", "caveat": "CAVEAT", "usage_guidance": "GUIDANCE"}[c["metadata"]["kind"]]
        lines.append(f"({kind}) {c['text']}")
    return "\n".join(lines)


# Phrases that would turn "may be eligible" into a promise.
_GUARANTEE_RX = re.compile(
    r"\b(you are entitled|you will (get|receive|be (paid|covered|treated free))|guarantee[sd]?|"
    r"you have (the|a) right|definitely|must pay you|is free of cost for you)\b", re.I)
_CITATION_RX = re.compile(r"\[([^\]]+)\]")


def _problems(text: str, allowed_titles: set[str]) -> list[str]:
    """Checks the generated text against the guardrails; returns feedback for a retry."""
    issues = []
    if _GUARANTEE_RX.search(text):
        issues.append("Your answer sounded like a guarantee. Use only 'may be eligible' / 'may be able to' language.")
    bad = {c for c in _CITATION_RX.findall(text) if c not in allowed_titles}
    if bad:
        issues.append(f"These citations are not valid sources: {sorted(bad)}. "
                      f"Cite only these exact titles: {sorted(allowed_titles)}.")
    return issues


def _generate(prompt: str) -> tuple[str, str]:
    """Return (text, model_used), falling back to lighter models if the primary is unavailable."""
    last_err = None
    for model in [GEN_MODEL, *GEN_FALLBACK_MODELS]:
        try:
            resp = _with_retry(lambda: client().models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.2)), attempts=2)
            return resp.text.strip(), model
        except genai_errors.APIError as e:  # overloaded, retired (404) etc. -> try the next model
            last_err = e
    raise last_err


def generate_explanation(injury_label: str, situation: str | None, facility: dict | None,
                         chunks: list[dict]) -> tuple[str, str]:
    # Built separately from the retrieval query so facility facts only appear when a source backs them.
    lines = [f"INJURY: {injury_label}"]
    if situation:
        lines.append(f"ABOUT THEM: {situation}")
    if facility:
        fac = f"CHOSEN HOSPITAL: {facility['name']} ({facility['type'].replace('_', ' ')})"
        if any(c["metadata"]["doc_id"] == "telangana_aarogyasri" for c in chunks):
            fac += (f"; Aarogyasri-empanelled: {'yes' if facility['aarogyasri_empanelled'] else 'no'}"
                    " (from demo data; tell them to confirm it at the hospital)")
        lines.append(fac)
    prompt = "\n".join(lines) + f"\n\nCONTEXT:\n{format_context(chunks)}"
    allowed = {c["metadata"]["title"] for c in chunks}
    for _ in range(2):
        text, model = _generate(prompt)
        issues = _problems(text, allowed)
        if not issues:
            return text, model
        prompt += "\n\nFix these problems in your previous answer and rewrite it:\n- " + "\n- ".join(issues)
    return text + "\n\n_These are possibilities, not guarantees — please confirm each one._", model


def fallback_explanation(sources: list[dict]) -> str:
    """Shown when Gemini is unreachable: names the relevant sources without paraphrasing them."""
    titles = "\n".join(f"- {s['title']}" for s in sources)
    return ("We couldn't generate a personalised explanation right now. These sources may be relevant "
            f"to your situation — ask the hospital's help desk or a legal aid clinic about them:\n{titles}")


def explain(injury_label: str, facility: dict | None = None, situation: str | None = None,
            situation_tags: list[str] | None = None) -> dict:
    ensure_index()
    tags = [t for t in dict.fromkeys(situation_tags or []) if t in SITUATIONS]
    phrases, must, exclude = situation_rules(tags)
    # Ticked situations first, then the user's free text, in one description.
    situation = ". ".join([*phrases, *([situation] if situation else [])]) or None
    query = build_situation_query(injury_label, facility, situation)
    # A non-empanelled facility voids Aarogyasri entirely -- always surface that warning.
    if facility and not facility["aarogyasri_empanelled"]:
        must = (*must, "telangana_aarogyasri")
    chunks = retrieve(query, must_include=must, exclude=exclude)
    sources = {}
    for c in chunks:
        m = c["metadata"]
        sources.setdefault(m["doc_id"], {"doc_id": m["doc_id"], "title": m["title"], "citation": m["citation"]})
    try:
        explanation, model_used = generate_explanation(injury_label, situation, facility, chunks)
        generated = True
    except genai_errors.APIError:
        explanation, model_used, generated = fallback_explanation(list(sources.values())), None, False
    return {
        "query": query,
        "explanation": explanation,
        "generated": generated,
        "sources": list(sources.values()),
        "situations": tags,
        "excluded_sources": list(exclude),
        "chunks": [{"id": c["id"], "kind": c["metadata"]["kind"], "similarity": c["similarity"],
                    "doc_score": c["doc_score"]} for c in chunks],
        "model": {"generation": model_used, "embedding": EMBED_MODEL},
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        print(f"Indexed {build_index()} chunks with {EMBED_MODEL}")
    elif cmd == "ask":
        from backend.db import get_connection, list_facilities
        from backend.triage import INJURIES
        injury = INJURIES[sys.argv[2]]["label"]
        fac = None
        if len(sys.argv) > 3:
            fac = next(f for f in list_facilities(get_connection()) if f["id"] == int(sys.argv[3]))
        out = explain(injury, fac, " ".join(sys.argv[4:]) or None)
        print(out["query"], "\nSOURCES:", [s["doc_id"] for s in out["sources"]], "\n\n" + out["explanation"])
