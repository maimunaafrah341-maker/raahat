#!/bin/sh
# Container entrypoint: seed data, start the API internally, then serve Streamlit on $PORT.
set -e

python data/seed_facilities.py

# API is internal only; Streamlit reaches it on localhost.
gunicorn --bind 127.0.0.1:5000 --workers 1 --threads 4 --timeout 120 backend.app:app &

# Wait for the API before the UI starts taking traffic.
for i in $(seq 1 30); do
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health')" 2>/dev/null && break
  sleep 1
done

# Build the vector index now (one Gemini embedding call) so the first user doesn't wait for it.
python -m backend.rag build || echo "Index build failed; it will be retried on first request."

exec streamlit run frontend/streamlit_app.py \
  --server.port "${PORT:-8501}" --server.address 0.0.0.0 \
  --server.headless true --browser.gatherUsageStats false
