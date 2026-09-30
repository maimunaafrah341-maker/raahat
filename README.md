# Raahat — emergency care finder (Hyderabad prototype)

Build with AI: Code for Communities — Track 3 (Smart Health & Supply Chain Resilience).

- **Demo video:** https://youtu.be/JqOIDOfVCZs
- **Live app:** https://raahat-9g7r.onrender.com (free Render plan: the first load after it has been idle can take about 50 seconds to wake up)

Given an injury and a location, Raahat ranks nearby facilities by whether they can
actually treat that injury (specialty + trauma capability + 24x7 emergency), then by
distance, and shows Aarogyasri empanelment on a colour-coded map. A Gemini RAG layer then
explains, in plain language, what the person *may* be eligible for (Clinical Establishments Act,
Paschim Banga judgment, Aarogyasri, Telangana BOCW Welfare Board) — always with citations and
"how to confirm" steps, never as a guarantee.

> **Hospital data is real but deliberately conservative.** `data/hospitals_real.json` lists 10 Hyderabad
> hospitals. Every specialty, emergency capability and Aarogyasri status comes from a cited public source
> (checked 27 Sep 2026); anything not confirmed is left out, so a hospital may be more capable than shown.
> Aarogyasri status is `official` (hospital's own site), `reported` (secondary sources) or unverified (`?`).
> Locations are from OpenStreetMap. The original synthetic set is still available: `python data/seed_facilities.py --demo`.

## Run

```bash
pip install -r requirements.txt
echo GEMINI_API_KEY=your-key > .env
python data/seed_facilities.py          # builds data/healthcare.db from the real, sourced hospital list
python -m backend.rag build              # embeds corpus/ into chroma_db/ (also auto-built on first use)
python -m backend.app                    # app + API on http://127.0.0.1:5000
```

## Deploy (Render)

`render.yaml` + `Dockerfile` run the whole app in one container: Flask (gunicorn) serves both
the web page and the API. In Render: **New → Blueprint →** pick this repo, then paste
your `GEMINI_API_KEY` when asked. The database is seeded and the vector index built on startup.
Peak memory for a full session is well inside the free tier's 512 MB (the API alone peaked at ~136 MB).

## API

- `GET  /api/injuries` — supported injury types
- `GET  /api/facilities` — all facilities
- `POST /api/triage` — `{"injury": "hand_finger", "lat": 17.36, "lng": 78.47, "radius_km": 20}`
- `POST /api/understand` — `{"text": "machine lo vellu tegipoyayi"}` → suggested injury, situations, life-threatening flag
- `GET  /api/situations` — situation tags the user can tick
- `POST /api/entitlements` — `{"injury": "hand_finger", "facility_id": 3, "situations": ["cant_pay"], "situation": "optional notes", "question": "optional", "history": [{"role": "user", "content": "..."}], "language": "te"}`

## Voice

For people who can't comfortably read or type: a mic button takes the description by voice (Telugu, Hindi,
Urdu or English, via the browser's speech recognition) and goes straight to understanding it — no extra tap.
"Read aloud" buttons on the first-aid card, the next-steps guide and each answer use the phone's own voice for
that language, skipping citation labels. If the phone has no voice for the language, the app says so instead of
reading Telugu/Urdu with an English voice. Support depends on the browser and phone (Chrome on Android works).

## First aid

`corpus/first_aid_*.md` and `corpus/danger_*.md` hold first-aid steps and danger signs for all 17 emergency types,
taken only from NHS, British Red Cross, St John Ambulance, British Heart Foundation, Macmillan and Government of India
guidance (sources listed in each file; 999 replaced by 108).
The app shows these steps as a fixed card — never generated — as soon as the injury is understood and in
"Your next steps"; Gemini only translates them (translation rejected unless numbers and step count survive).
They are also in the vector store, so follow-up questions like "should I put the finger in ice?" are answered
from them with a citation. Anything beyond them gets "ask a doctor or call 108".

## Illness, pregnancy and other emergencies

Besides injuries, Raahat covers pregnancy problems, a seriously unwell baby or child, fever during
chemotherapy, stroke, seizures, severe allergic reactions, snake bites, poisoning and low blood sugar
(17 emergency types). The patient can also be tagged as **pregnant, on chemotherapy, diabetic or a young
child** — typed, spoken ("amma ki chemo nadustundi, 38.5 jwaram") or ticked. Each tag adds a fixed
**danger-signs card** ("get help now if you see any of these"), tells the person what to tell the
ambulance crew, and moves hospitals with the relevant department (obstetrics, pediatrics) up within their tier.

- Sources: NHS (pregnancy, baby/child, stroke, seizure, anaphylaxis, poisoning, low blood sugar),
  Macmillan Cancer Support (sepsis during chemotherapy), and the Government of India's Standard Treatment
  Guidelines for Snakebite (MoHFW, 2016), which warns against tourniquets, cutting and herbal remedies.
- Where our hospital sources don't say which hospitals have the specialist team (e.g. a stroke unit), the app
  says so and ranks by 24x7 emergency care and distance instead of implying a specialist match.
- For follow-up questions, legal and medical sources are retrieved as separate pools (a first-aid match
  otherwise always outranks the law), so "is 37.8 dangerous? and can they refuse if we can't pay?" gets both
  halves answered, while a purely medical question gets no unasked legal points.

## Conversation memory

Each person's case (injury, hospital, situations, notes) and their questions and answers are saved **only in
their own browser** (`localStorage`), never on the server, so they can close the page and come back to ask a
follow-up. Each question sends the case plus the last 6 messages; the model answers the question asked (each
one, if several), uses the history only to resolve follow-ups, and says plainly when something is outside its
sources instead of guessing. "Start a new case" clears it.

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
  `backend/i18n.py`, not machine-translated at runtime. `tests/test_i18n.py` checks every key
  exists in every language and nothing was left in English.
- Explanations are generated and checked **in English first**, then translated by Gemini. The
  translation is rejected (English shown instead) unless every source citation and every number
  or amount survives unchanged. Translations are labelled as machine translation, with the English
  original one tap away.
- "Tell us what happened" accepts a description in any of the four languages, native script or
  romanized. Gemini structured output maps it onto the app's own injury/situation lists (so it can't
  invent a category) and only pre-fills the form for the user to confirm.
- Not yet reviewed by native speakers. "Why this ranking" reasons are still English only.
