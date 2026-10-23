"""Translate every first-aid and danger-signs card once and save it to data/card_translations.json.

The cards are fixed, reviewed text, so translating them at request time only adds waiting and a
chance of falling back to English when Gemini is busy. Each saved translation is keyed to a hash of
the English it came from: edit a corpus card and its old translation is ignored until you rerun this.

    python data/translate_cards.py          # translate missing or outdated cards
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import first_aid, rag  # noqa: E402

LANGS = ("hi", "te", "ur")


def main() -> int:
    saved = first_aid.load_saved()
    docs = sorted(set(rag.FIRST_AID_DOCS.values()) | set(rag.CONDITION_DOCS.values()))
    todo = [(d, lang) for d in docs for lang in LANGS
            if saved.get(f"{d}/{lang}", {}).get("source") != first_aid.source_hash(first_aid._parse(d))]
    print(f"{len(todo)} of {len(docs) * len(LANGS)} cards need translating")
    failed, lock = [], threading.Lock()

    def translate(job):
        doc_id, lang = job
        card = first_aid._parse(doc_id)
        for attempt in range(4):
            steps = first_aid._translate_list(card["steps"], lang)
            cautions = first_aid._translate_list(card["cautions"], lang) if steps is not None else None
            if steps is not None and cautions is not None:
                with lock:  # save after every card, so an interrupted run keeps its progress
                    saved[f"{doc_id}/{lang}"] = {"source": first_aid.source_hash(card), "steps": steps,
                                                 "cautions": cautions}
                    first_aid.SAVED_FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=1, sort_keys=True),
                                                    encoding="utf-8")
                print("ok  ", doc_id, lang, flush=True)
                return
            time.sleep(5 * (attempt + 1))
        failed.append(job)
        print("FAIL", doc_id, lang, flush=True)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(translate, todo))
    print(f"done; {len(failed)} failed{': ' + str(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
