#!/bin/sh
# Container entrypoint: seed data, build the vector index, then serve the app on $PORT.
set -e

python data/seed_facilities.py

# One Gemini embedding call, done now so the first user doesn't wait for it.
python -m backend.rag build || echo "Index build failed; it will be retried on first request."

exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 8 --timeout 120 backend.app:app
