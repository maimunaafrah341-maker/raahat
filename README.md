# Raahat — emergency care finder (Hyderabad prototype)

Build with AI: Code for Communities — Track 3 (Smart Health & Supply Chain Resilience).

Given an injury and a location, Raahat ranks nearby facilities by whether they can
actually treat that injury (specialty + trauma capability + 24x7 emergency), then by
distance, and shows Aarogyasri empanelment on a colour-coded map. A Gemini RAG layer then
explains, in plain language, what the person *may* be eligible for (Clinical Establishments Act,
Paschim Banga judgment, Aarogyasri, Telangana BOCW Welfare Board) — always with citations and
"how to confirm" steps, never as a guarantee.

> Facility data is **synthetic**: names are fictional, localities are real Hyderabad areas.

## Run

```bash
pip install -r requirements.txt
echo GEMINI_API_KEY=your-key > .env
python data/seed_facilities.py          # builds data/healthcare.db
python -m backend.rag build              # embeds corpus/ into chroma_db/ (also auto-built on first use)
python -m backend.app                    # Flask API on :5000
streamlit run frontend/streamlit_app.py  # UI (second terminal)
```

## API

- `GET  /api/injuries` — supported injury types
- `GET  /api/facilities` — all facilities
- `POST /api/triage` — `{"injury": "hand_finger", "lat": 17.36, "lng": 78.47, "radius_km": 20}`
- `GET  /api/situations` — situation tags the user can tick
- `POST /api/entitlements` — `{"injury": "hand_finger", "facility_id": 15, "situations": ["construction_worker"], "situation": "optional free text"}`

## How the RAG layer stays accurate

- Each corpus document is split into labelled sections (key fact / caveat / usage guidance) and
  embedded with `gemini-embedding-001`.
- Retrieval ranks documents by their best-matching section and keeps only those within 0.04
  cosine similarity of the top one, so the answer draws on 1–3 of the 4 sources.
- A selected document always brings its caveat with it; a non-empanelled hospital always pulls in
  the Aarogyasri empanelment warning.
- Ticked situations force in the sources that always apply to them (e.g. "turned away" → Clinical
  Establishments Act + Paschim Banga), and gate out ones that can't (BOCW is dropped unless a
  worker situation is ticked).
- Gemini output is checked in code: guarantee language or a citation that isn't a retrieved source
  triggers a rewrite. If Gemini is unavailable, the app falls back to listing the relevant sources.

## Languages

The UI and the entitlement explanations are available in English, Hindi, Telugu and Urdu
(approach adapted from [Athena](https://github.com/maimunaafrah341-maker/Athena)).

- Fixed UI text, including the 108 banner and empanelment warnings, is hand-written in
  `frontend/i18n.py`, not machine-translated at runtime. `tests/test_i18n.py` checks every key
  exists in every language and nothing was left in English.
- Explanations are generated and checked **in English first**, then translated by Gemini. The
  translation is rejected (English shown instead) unless every source citation and every number
  or amount survives unchanged. Translations are labelled as machine translation, with the English
  original one tap away.
- Not yet reviewed by native speakers. "Why this ranking" reasons are still English only.
