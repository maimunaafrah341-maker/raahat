You are writing ONE file: `frontend/streamlit_app.py` for an existing project. Output ONLY the complete Python source of that file in a single ```python code block. No explanations, no setup steps, no other files, no text before or after the code block.

## What the app is
"Raahat" — an emergency care finder for Hyderabad, Telangana (India). A person who is injured (or helping someone injured) picks their injury and location; the app shows which nearby hospitals can actually treat that injury on a colour-coded map, and then explains in plain language what financial/legal help they MAY be eligible for. Users are often low-income workers under stress, on a phone. Clarity and calm beat decoration.

## Hard constraints
- Python 3.11, Streamlit >= 1.50. Allowed imports ONLY: `os`, `requests`, `streamlit`, `folium`, `streamlit_folium` (`st_folium`). No other packages, no custom JS/HTML components beyond `st.markdown(..., unsafe_allow_html=True)` for small styling.
- The backend is a separate Flask API. Base URL: `API_URL = os.getenv("RAAHAT_API_URL", "http://127.0.0.1:5000")`. Never call Gemini or any other external API directly. Never hardcode facility data, injury lists, legal text, scheme amounts or phone numbers — everything comes from the API, except the fixed UI texts listed under "Required UI text".
- Display the `explanation` string from `/api/entitlements` EXACTLY as returned (render as markdown). Do not summarise, rewrite, shorten, translate or add to it. Do not add any legal, scheme or medical claims of your own anywhere in the UI.
- Handle the backend being down (connection error) with a clear `st.error` and `st.stop()`. Handle non-2xx responses by showing the `error` field from the JSON body. `/api/entitlements` can take up to 60 s and can return HTTP 503 — use `timeout=90` and a spinner.
- Use `st.session_state` so the map and results survive reruns; clear the stored entitlements result whenever a new search is run. Pass `returned_objects=[]` to `st_folium` to avoid rerun loops.
- Must work at phone width (Streamlit `layout="wide"` is fine, but content must stack sensibly; put inputs in the main area on top, not only the sidebar).

## API contract (exact field names)

`GET /api/injuries` → `[{"key": "hand_finger", "label": "Hand / finger injury (cut, crush, partial amputation)"}, ...]`

`POST /api/triage` body `{"injury": "<key>", "lat": 17.36, "lng": 78.47, "radius_km": 20}` →
```json
{
  "injury": {"key": "hand_finger", "label": "Hand / finger injury (...)"},
  "origin": {"lat": 17.3616, "lng": 78.4747},
  "results": [
    {
      "id": 10, "rank": 1, "name": "Himayatnagar Hand & Microsurgery Centre",
      "locality": "Himayatnagar", "district": "Hyderabad", "lat": 17.401, "lng": 78.487,
      "type": "empanelled_private",
      "specialties": ["emergency_medicine", "orthopedics", "hand_surgery", "plastic_surgery"],
      "trauma_level": 2, "trauma_label": "intermediate",
      "emergency_24x7": true, "aarogyasri_empanelled": true, "is_synthetic": true,
      "distance_km": 4.57, "score": 85.4,
      "tier": "specialist",
      "reasons": ["Has hand surgery, plastic surgery", "24x7 emergency department"]
    }
  ]
}
```
`results` is already sorted best-first; do not re-sort. `type` ∈ `govt | charitable | empanelled_private | private`. `tier` ∈ `specialist | can_manage | stabilize | unsuitable`.

`POST /api/entitlements` body `{"injury": "<key>", "facility_id": 10, "situation": "<optional free text, max 500 chars>"}` →
```json
{
  "explanation": "* bullet one ... [Clinical Establishments Act, 2010 (Telangana Rules, 2011)]\n\n* bullet two ...",
  "generated": true,
  "sources": [{"doc_id": "clinical_establishments_act", "title": "Clinical Establishments Act, 2010 (Telangana Rules, 2011)", "citation": "The Clinical Establishments (Registration and Regulation) Act, 2010 ..."}],
  "model": {"generation": "gemini-3.8-flash", "embedding": "gemini-embedding-001"}
}
```
`generated` is false when the AI was unavailable (explanation is then a fallback message; still show it as-is). `model.generation` may be null.

## Screens / layout (single page, top to bottom)
1. Header: app name "Raahat", tagline "Find the right emergency care — and know your options", small caption "Hyderabad district · prototype".
2. Required UI text (always visible, near the top):
   - A prominent red box: **"Life-threatening emergency? Call 108 for an ambulance first."**
   - A warning: "Demo data: facility names are fictional and capabilities/empanelment are synthetic. Do not use for real medical decisions."
3. Search form (main area, in a bordered container):
   - Injury select (from `/api/injuries`, show `label`; cache with `st.cache_data(ttl=300)`).
   - Location select with these Hyderabad localities (name → lat, lng): Afzalgunj (17.3713, 78.4804), Amberpet (17.3920, 78.5170), Banjara Hills (17.4156, 78.4347), Begumpet (17.4440, 78.4630), Chandrayangutta (17.3200, 78.4800), Charminar (17.3616, 78.4747) [default], Golconda (17.3833, 78.4011), Himayatnagar (17.4010, 78.4870), Khairatabad (17.4120, 78.4610), Malakpet (17.3764, 78.5006), Mehdipatnam (17.3960, 78.4390), Musheerabad (17.4180, 78.5000), Nampally (17.3924, 78.4675), Santoshnagar (17.3480, 78.5140), Secunderabad (17.4399, 78.4983), Tolichowki (17.3990, 78.4150).
   - An expander "Use exact coordinates" with a checkbox to override lat/lng via number inputs (4 decimals).
   - Radius slider 2–30 km, default 20.
   - Primary button "Find hospitals".
4. Results summary line: injury label + count of facilities, plus 3 small metric tiles: number of "specialist" tier results, nearest specialist distance (km), number of Aarogyasri-empanelled specialists.
5. Map (left, ~60%) + ranked list (right, ~40%); stacked on narrow screens.
   - Folium map, `tiles="cartodbpositron"`, centred on origin, zoom 13. Blue "You are here" marker (`icon="user"`).
   - Facility markers coloured by tier: specialist=green, can_manage=orange, stabilize=red, unsuitable=lightgray. Icon: `ok-sign` if `aarogyasri_empanelled` else `remove-sign`. Tooltip `#rank name`. Popup (max_width 300): name, tier text, type label, distance, empanelment line, reasons as bullets.
   - A legend under the map explaining the four colours and the ✓/✗ symbol.
   - Ranked list: top 8 results as bordered cards: `#rank name`, coloured tier text, "type · locality · distance km", an empanelment line, and an expander "Why this ranking" listing `reasons`.
   - Tier texts: specialist "Best match — has the right specialists"; can_manage "Can likely manage — related specialty"; stabilize "Emergency care only — will likely refer you on"; unsuitable "Not equipped for this injury".
   - Type labels: govt "Government", charitable "Charitable", empanelled_private "Private (Aarogyasri-empanelled)", private "Private".
   - Empanelment lines: true → "✅ Listed as Aarogyasri-empanelled — confirm at the hospital's Aarogyasri desk"; false → "❌ Not Aarogyasri-empanelled — Aarogyasri cashless treatment won't apply here".
6. Section "What you may be eligible for":
   - Caption: "Generated by Gemini from the Clinical Establishments Act, a Supreme Court judgment, Aarogyasri and the BOCW Welfare Board rules. This is general information, not legal advice."
   - Select "Hospital you are going to / went to" (options = results, label `#rank name`, default first).
   - Optional text input "Anything else about you?" with placeholder "e.g. daily wage construction worker, BPL ration card, was turned away".
   - Button "Explain my options" → spinner "Checking schemes and laws that may apply…" → POST `/api/entitlements`.
   - Show `explanation` verbatim in a bordered container. Below it an expander "Sources used" listing each source's bold `title` and its `citation`, and a small caption "Generated by {model.generation} · retrieval via {model.embedding}" when `model.generation` is not null.
7. Before any search: an `st.info` telling the user to choose injury + location and press "Find hospitals".

## Style
Calm and trustworthy: white/very light background, one teal accent (#0f766e) for primary buttons and headings, generous spacing, large readable text (base 16–17px), no emojis except ✅ ❌ and the ones specified above, no gradients, no animations. Keep custom CSS short (under 40 lines) and only via one `st.markdown("<style>…</style>", unsafe_allow_html=True)` call.

## Code quality
Small helper functions (`fetch_injuries`, `run_search`, `build_map`, `render_card`, `render_entitlements`), constants at the top, no dead code, no print statements, comments only where non-obvious.

Remember: reply with ONLY the complete `frontend/streamlit_app.py` in one ```python code block.
