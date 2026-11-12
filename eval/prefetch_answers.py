"""Warm the Gemini response cache for one system (retrieval + Gemini only, no NLI models), so that
run_generation_eval.py can later score those answers from cache. Useful when Gemini is slow: run it in parallel with
the main evaluation. It writes nothing to the results file.

Run:  <venv>/python eval/prefetch_answers.py after
"""
import logging
import sys
import time

from rag_common import EVAL, history_for, load_manifest, load_questions

from App.rag.llm import QuotaExhausted
from App.rag.pipeline import RAGService
from run_generation_eval import SYSTEMS

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
name = sys.argv[1]
svc = RAGService(SYSTEMS[name])
qs = load_questions()
by_id = {q["id"]: q for q in qs}
manifest = load_manifest()
docs = {}
for q in qs:
    d = q["document"]
    if d not in docs:
        docs[d] = svc.ingest((EVAL / manifest[d]["file"]).read_bytes(), title=manifest[d]["title"])["doc_id"]
    try:
        r = svc.ask(docs[d], q["question"], history_for(q, by_id))
    except QuotaExhausted as e:
        print("quota exhausted:", str(e)[:200], flush=True)
        break
    print(f"prefetch {name} {q['id']} cached={r['usage']['cached']} llm_ms={r['latency_ms']['llm']}", flush=True)
    if not r["usage"]["cached"]:
        time.sleep(4)
print("prefetch done", flush=True)
