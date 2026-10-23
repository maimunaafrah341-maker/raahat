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

> **Hospital data is real but deliberately conservative.** `data/hospitals_real.json` lists 19 researched
> Hyderabad hospitals. Every specialty, emergency capability, phone number and Aarogyasri status comes from a
> cited public source; anything not confirmed is left out, so a hospital may be more capable than shown.
> Another 700 hospitals from OpenStreetMap (`data/hospitals_osm.json`) are shown as "not yet checked — call
> first", only after the researched ones. Aarogyasri status is `official` (hospital or government site),
> `reported` (secondary sources) or unverified (`?`). The original synthetic set is still available:
> `python data/seed_facilities.py --demo`.

## Screenshots

| | |
|---|---|
| ![Home page on a computer](Raahat%20screenshots/01-home-desktop.png) **1. Home:** 108 first, helplines that call when tapped, then "what happened?" | ![Home page on a phone](Raahat%20screenshots/02-home-phone.png) **2. On a phone:** a 108 bar on every screen |
| ![Describing the emergency in Telugu](Raahat%20screenshots/03-describe-in-telugu-ai-fills-the-form.png) **3. Describe it in Telugu** (typed or spoken): the AI fills in the emergency and the area, then searches | ![Map and hospital list](Raahat%20screenshots/04-results-map-and-hospital-list.png) **4. Results:** hospitals that can treat it first, colour-coded on the map |
| ![Hospital card](Raahat%20screenshots/05-hospital-card-with-trust-level.png) **5. Hospital card:** why it matches, Aarogyasri status, when it was checked | ![Closer hospitals not yet checked](Raahat%20screenshots/06-closer-hospitals-not-yet-checked-call-first.png) **6. On the city's edge:** closer hospitals we haven't checked yet, with what to ask when you call |
| ![Next steps](Raahat%20screenshots/07-next-steps-call-directions-staff-card.png) **7. Your next steps:** first aid, where to go, documents, rights, payment | ![Documents to carry](Raahat%20screenshots/08-documents-to-carry-chemotherapy.png) **8. Documents to carry** (chemotherapy: ration card, Aarogyasri card, Aadhaar, referral letter) |
| ![Paying for treatment](Raahat%20screenshots/09-paying-with-or-without-aarogyasri-card.png) **9. Paying for treatment,** with or without an Aarogyasri card | ![Answer with citations](Raahat%20screenshots/10-answer-with-citations-and-dates.png) **10. Answers cite their sources,** with the date each was checked |
| ![I'm not sure](Raahat%20screenshots/11-im-not-sure-instead-of-guessing.png) **11. "I'm not sure"** when the sources don't cover a question, instead of guessing | ![Mental health crisis](Raahat%20screenshots/12-mental-health-crisis-helplines.png) **12. Mental health crisis:** 108, Tele-MANAS 14416 and Roshni as call buttons |
| ![Show to hospital staff](Raahat%20screenshots/13-show-to-hospital-staff-telugu.png) **13. Show to hospital staff:** the patient's needs in Telugu and English | ![Offline mode](Raahat%20screenshots/14-offline-mode-no-internet.png) **14. Offline:** the saved hospital list still works with no internet |

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

Two optional settings for collecting validation data:

- `DATABASE_URL` — a Postgres URL (a free Neon or Supabase database works). Render's free disk is wiped
  on every restart, so without it usage events only survive in the logs (lines starting `RAAHAT_EVENT`).
- `ADMIN_TOKEN` — unlocks `GET /api/admin/stats?token=…` (headline numbers) and
  `GET /api/admin/events.csv?token=…` (every event). Without it both return 404.

## Safety rails

- **Citations with dates.** Every answer names the documents it cites and when each was last checked
  (the `Last verified:` line at the top of each `corpus/*.md`; update it when you re-check a source).
  Hospital cards show when their details were checked and warn after 90 days.
- **"I'm not sure" instead of guessing.** A question whose closest source passage scores below
  `LOW_CONFIDENCE` (0.64, `backend/rag.py`) gets "please ask at the hospital desk" and is never sent to
  the model. Calibrated on in-scope vs off-topic questions in English, Telugu, Hindi and Urdu.
- **108 everywhere.** A large call button in the hero, and a call bar fixed to the bottom of every phone screen.
- **Documents to carry** (`backend/checklist.py`), built from the emergency, the patient and their situation.
  Items backed by a corpus source show it; the rest are marked as practical tips.

- **Show to hospital staff.** A full-screen card with the emergency, who the patient is and "please
  stabilise first" (plus police-formalities and road-accident lines when they apply), in the person's
  language with English underneath. Fixed, hand-written sentences only; nothing generated.
- **Call the hospital.** Only numbers taken from the hospital's own site or the WHO institute directory,
  each with its source (`phone` in `data/hospitals_real.json`). Hospitals without a verified number say so.
- **Works without signal.** `frontend/web/sw.js` keeps the page, the hospital list and every first-aid
  card on the phone. Offline, a search lists hospitals by distance only, clearly marked as unranked.

- **Voice understood by Gemini.** The mic records until the person stops talking, converts the audio to
  16 kHz WAV and sends it to `/api/understand_audio`. Gemini returns what it heard (in the speaker's
  script), the emergency, who the patient is, their situation and their area, plus a one-line summary
  to confirm. Tested on Telugu, Hindi (code-mixed), Urdu and English recordings. If the area is known,
  the search runs straight away. Phones that can't record fall back to the browser's own recognition.
- **Mental health crisis.** An emergency type with Tele-MANAS (14416, free, 24x7), Roshni (Hyderabad)
  and 108 as call buttons, and sourced steps (NHS). Suicidal or self-harm talk counts as life-threatening.
- **Paying for treatment, with or without a card**: what to do at the Aarogya Mithra desk in each case.
- **Free / low-cost hospitals first**: a tick box (on by itself when someone says they can't pay or have a
  ration card) puts government, charitable and Aarogyasri hospitals first, but only among hospitals equally
  able to treat the emergency. A cheaper hospital never moves above a better-equipped one.

## Gemini quotas

Understanding (typed or spoken) uses fast "lite" models first (`UNDERSTAND_MODELS` in
`backend/understanding.py`, ~4-8 s). On the free tier `gemini-3.8-flash` allows only 20 requests a day,
so for real use enable billing on the API key; the fallback chains keep the app answering meanwhile.

## Researching hospitals yourself

Every hospital card shows how much Raahat has checked it:

- ✅ **Verified by phone** (date): someone called and asked.
- 📄 **Researched from public sources** (date): every capability is backed by a cited link.
- ❔ **Not yet checked**: only listed from OpenStreetMap (`data/fetch_osm_hospitals.py`). Shown after
  every researched hospital, nearest 10 only, with "call first" and a script of what to ask.

To move a hospital from ❔ to 📄 without calling anyone:

1. Copy `data/research_template.csv` and open it in Excel or Google Sheets; one row per hospital.
2. Research from these sources, and put every link you used in `sources` (`label|https://link`,
   separated by `;`):
   - **The hospital's own website**: departments page, "24x7 emergency / casualty / trauma", contact page.
   - **Google Maps listing**: "Open 24 hours", phone number, photos of an Emergency sign, recent reviews
     that mention the emergency ward.
   - **PM-JAY hospital search** (hospitals.pmjay.gov.in, Telangana → Hyderabad; needs a captcha):
     empanelment and specialities. This counts as `official` for Aarogyasri.
   - **NABH accredited hospitals list** (nabh.co): accreditation, often lists emergency services.
   - News reports, for things like new trauma centres or Aarogyasri suspensions.
3. Fill each column only with what a source says. When unsure, write `unknown` or leave it out;
   a gap is safer than a guess.
   - `emergency_24x7`: `yes` only if a source says 24x7 / 24 hours emergency or casualty.
   - `specialties`: only departments the hospital itself lists, from:
     `emergency_medicine general_medicine general_surgery orthopedics hand_surgery plastic_surgery
     neurosurgery burns cardiology pediatrics obstetrics ophthalmology oncology psychiatry`.
   - `trauma_level`: 3 = major trauma centre (neurosurgery, ICU and blood bank stated), 2 = casualty
     with surgery/orthopaedics, 1 = basic emergency care, 0 = none.
   - `aarogyasri`: `yes`/`no` with `aarogyasri_evidence` = `official` (hospital or government site)
     or `reported` (news, lists); otherwise `unknown`.
   - `phone` + `phone_kind` (`emergency`, `main` or `helpline`) + `phone_source_url`.
   - `lat`/`lng`: leave blank if the name matches the OpenStreetMap list; otherwise copy them from
     Google Maps (right-click the place → the numbers at the top).
   - `verified_by_phone`: `yes` only if you called and they confirmed the details.
4. Download as CSV and run:
   ```
   python data/import_research.py path/to/your.csv
   python data/seed_facilities.py
   ```
   Bad rows are listed with the reason and skipped. Commit `data/hospitals_real.json` and push to deploy.

Start with the areas people search most (the admin stats show them), and the hospitals that come up
as ❔ near those areas.

## Areas

`data/localities.json`: 106 Hyderabad areas in six zones, coordinates from OpenStreetMap (Nominatim).
Ambiguous names (e.g. two places called Bandlaguda) are left out rather than guessed.

## What is logged (anonymously)

`backend/analytics.py`: emergency type, language, area (a named locality, or GPS rounded to ~1 km),
result counts, questions with long numbers and emails removed, "was this helpful?", 108/directions/share
taps, and "something wrong with this hospital" reports. No IP address, user agent or exact location.
A random id per case groups one person's events without identifying them.

## Hospital data

`data/hospitals_real.json` can also record, per hospital, the specialities the PM-JAY / Aarogyasri
registry lists it for (`scheme_specialties` + `scheme_source` + `pmjay_id`) and its own `checked_on`.
The official search is <https://hospitals.pmjay.gov.in> (State: Telangana, District: Hyderabad); it needs
a captcha, so entries are checked by hand.

## API

- `GET  /api/injuries` — supported injury types
- `GET  /api/facilities` — all facilities
- `POST /api/triage` — `{"injury": "hand_finger", "lat": 17.36, "lng": 78.47, "radius_km": 20, "low_cost_first": false}`
- `POST /api/understand` — `{"text": "machine lo vellu tegipoyayi"}` → suggested injury, situations, life-threatening flag
- `GET  /api/situations` — situation tags the user can tick
- `POST /api/entitlements` — `{"injury": "hand_finger", "facility_id": 3, "situations": ["cant_pay"], "situation": "optional notes", "question": "optional", "history": [{"role": "user", "content": "..."}], "language": "te"}` → also `low_confidence`, and `verified` on each source
- `GET  /api/checklist` — rules for the documents-to-carry card
- `POST /api/speak` — `{"text": "108కి ఫోన్ చేయండి.", "language": "te"}` → WAV audio (up to 600 characters)
- `POST /api/event` — `{"kind": "feedback|action|report", "value": "...", "session": "..."}` (closed vocabularies, see `backend/analytics.py`)

## Voice

For people who can't comfortably read or type: a mic button takes the description by voice (Telugu, Hindi,
Urdu or English, via the browser's speech recognition) and goes straight to understanding it — no extra tap.
"Read aloud" buttons on the first-aid card, the next-steps guide and each answer use the phone's own voice for
that language when it has one, skipping citation labels. Most phones and laptops have no Telugu or Urdu voice,
so then the page asks `/api/speak`, which reads the text with Gemini text-to-speech (`backend/speech.py`) a sentence
or two at a time: the first words play in about 4 seconds. Chunks are cached, so first-aid cards that many people
read cost nothing after the first time, and each visitor is limited to 150 chunks per 10 minutes.

## First aid

`corpus/first_aid_*.md` and `corpus/danger_*.md` hold first-aid steps and danger signs for all 17 emergency types,
taken only from NHS, British Red Cross, St John Ambulance, British Heart Foundation, Macmillan and Government of India
guidance (sources listed in each file; 999 replaced by 108).
The app shows these steps as a fixed card — never generated — as soon as the injury is understood and in
"Your next steps". The Hindi, Telugu and Urdu versions are translated once by `data/translate_cards.py` and saved in
`data/card_translations.json` (rejected unless numbers and step count survive), so cards appear instantly in every
language, even when Gemini is busy. Each translation is tied to the English it came from: after editing a card,
rerun `python data/translate_cards.py`; until then that card is translated live.
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
