# Raahat — emergency care finder (Hyderabad prototype)

Build with AI: Code for Communities — Track 3 (Smart Health & Supply Chain Resilience).

Given an injury and a location, Raahat ranks nearby facilities by whether they can
actually treat that injury (specialty + trauma capability + 24x7 emergency), then by
distance, and shows Aarogyasri empanelment on a colour-coded map.

> Facility data is **synthetic**: names are fictional, localities are real Hyderabad areas.

## Run

```bash
pip install -r requirements.txt
python data/seed_facilities.py          # builds data/healthcare.db
python -m backend.app                    # Flask API on :5000
streamlit run frontend/streamlit_app.py  # UI (second terminal)
```

## API

- `GET  /api/injuries` — supported injury types
- `GET  /api/facilities` — all facilities
- `POST /api/triage` — `{"injury": "hand_finger", "lat": 17.36, "lng": 78.47, "radius_km": 20}`
