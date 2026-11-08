# Raahat — solution pitch

Great Indian AI Internship Challenge

## Problem

In an emergency in Hyderabad, many people can't type or read English, don't know which nearby hospital can
actually treat their case, and don't know what schemes like Aarogyasri may cover.

## Solution

The person speaks in Telugu, Hindi or Hinglish (Urdu and English work too). Raahat works out the emergency and
the area and shows them to confirm. It ranks hospitals by whether they can treat that emergency (specialty,
trauma care, 24x7), then by distance. A "free / low-cost first" option puts government, charitable and
Aarogyasri hospitals first among those equally able to treat it. First-aid steps are fixed text from NHS, Red
Cross and Government of India guidance, never generated. Questions about schemes and rights are answered only
from verified documents, with sources, or with "I'm not sure". Answers can be read aloud.

## How Gnani is used

- **Prisma (speech to text):** the first spoken description and spoken follow-up questions, in Telugu, Hindi and
  English, including mixed Hindi and English.
- **Timbre (text to speech):** reads first aid, next steps and answers aloud in Telugu and Hindi.
- Gemini takes over if Gnani is unavailable. Urdu uses Gemini only, as Gnani has no Urdu.

## How it works

Flask backend, plain JavaScript page. Gemini understands the description and writes answers through a RAG
pipeline over 11 verified legal, scheme and first-aid documents. 19 researched hospitals are joined by 700 from
OpenStreetMap, marked "not yet checked — call first". Deployed on Render.

## What testing with family changed

- A searchable area box that accepts spelling variants and Telugu, Hindi or Urdu script, with "Use my location".
- Three example buttons under the mic.
- iPhone recordings failed with "decoding failed"; Safari now records in one piece, and it works.

## Limits and next steps

Raahat is a prototype, not a replacement for 108. Translations have not yet been
reviewed by medical professionals. Next, we plan to test it with ASHA workers or NGO volunteers.

## Links

- Live app: https://raahat-9g7r.onrender.com (free tier, so the first load can take about a minute)
- Demo video: https://youtu.be/zD166e7fdb4
