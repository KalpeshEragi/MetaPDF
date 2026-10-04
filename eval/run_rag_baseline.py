"""Baseline RAG benchmark: runs the UNMODIFIED production functions of App/chat_app.py.

Per document: get_pdf_text -> get_text_chunks -> get_vector_store (embed + FAISS save) exactly as `index()` does on upload;
per question: load_vector_store -> similarity search (k = production default 4; with_score only adds scores to the identical
call) -> get_conversational_chain -> chain(...) exactly as `index()` does on a question.

Run (project interpreter, repo root):  <project>/venv/Scripts/python.exe eval/run_rag_baseline.py [--ids att-01 ...]
Raw output (append-only, resumable): eval/results/rag_baseline_raw.jsonl ; ingestion: eval/results/rag_ingestion.json
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("GOOGLE_API_KEY", "unused-local-baseline")  # production insists on a key at import; never used here
os.environ.setdefault("FLASK_SECRET_KEY", "eval")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
os.chdir(ROOT)

import compat_shims  # noqa: E402

SHIM_CONFIG = compat_shims.install()
import App.chat_app as chat_app  # noqa: E402  (production module, unmodified)
from flask import Flask  # noqa: E402

EVAL = ROOT / "eval"
RES = EVAL / "results"
WORK = RES / "_work"
RES.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)
RAW = RES / "rag_baseline_raw.jsonl"
ING = RES / "rag_ingestion.json"
norm = lambda s: re.sub(r"\s+", " ", s).strip()

ap = argparse.ArgumentParser()
ap.add_argument("--ids", nargs="*")
ap.add_argument("--docs", nargs="*")
args = ap.parse_args()

manifest = {d["id"]: d for d in json.loads((EVAL / "corpus" / "manifest.json").read_text(encoding="utf-8"))["documents"]}
questions = [json.loads(l) for l in (EVAL / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
qbydoc = {}
for q in questions:
    qbydoc.setdefault(q["document"], []).append(q)
done = set()
if RAW.exists():
    done = {json.loads(l)["id"] for l in RAW.read_text(encoding="utf-8").splitlines() if l.strip()}
ingestion = json.loads(ING.read_text(encoding="utf-8")) if ING.exists() else {}

flask_app = Flask("metapdf_eval", root_path=str(WORK))  # production writes <root_path>/data/faiss_index (isolated from the repo)


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def pct(a):  # not used for scoring; just convenience in logs
    return round(100 * a, 1)


for doc_id, meta in manifest.items():
    if args.docs and doc_id not in args.docs:
        continue
    todo = [q for q in qbydoc.get(doc_id, []) if q["id"] not in done and (not args.ids or q["id"] in args.ids)]
    if not todo:
        continue
    print(f"=== {doc_id}: {len(todo)} questions to run", flush=True)
    pdf_bytes = (EVAL / meta["file"]).read_bytes()

    # ---------------- ingestion (what index() does on upload)
    compat_shims.reset_calls()
    t0 = time.perf_counter()
    raw_text = chat_app.get_pdf_text([io.BytesIO(pdf_bytes)])
    t_extract = time.perf_counter() - t0
    t0 = time.perf_counter()
    chunks = chat_app.get_text_chunks(raw_text)
    t_chunk = time.perf_counter() - t0
    with flask_app.app_context():
        t0 = time.perf_counter()
        vs = chat_app.get_vector_store(chunks)
        t_index = time.perf_counter() - t0
        idx_dir = Path(flask_app.root_path) / "data" / "faiss_index"
        idx_bytes = dir_size(idx_dir) if idx_dir.exists() else None
    emb = [c for c in compat_shims.CALLS if c["type"] == "embedding"]
    lens = [len(c) for c in chunks]
    ingestion[doc_id] = {
        "pages": meta["pages"], "raw_chars": len(raw_text), "raw_words": len(raw_text.split()),
        "extraction_seconds": round(t_extract, 3), "n_chunks": len(chunks), "configured_chunk_size": 10000,
        "configured_chunk_overlap": 1000, "chunk_chars_min": min(lens) if lens else 0, "chunk_chars_max": max(lens) if lens else 0,
        "chunk_chars_mean": round(sum(lens) / len(lens), 1) if lens else 0, "chunking_seconds": round(t_chunk, 4),
        "est_chunk_tokens_total_chars_div_4": sum(lens) // 4,
        "embedding_http_calls": len(emb), "embedding_texts": sum(c["n_texts"] for c in emb),
        "embedding_prompt_tokens_provider_reported": sum((c["prompt_tokens"] or 0) for c in emb),
        "embedding_seconds_sum": round(sum(c["seconds"] for c in emb), 3), "index_build_seconds_total": round(t_index, 3),
        "index_size_bytes": idx_bytes, "vector_store_created": vs is not None,
    }
    ING.write_text(json.dumps(ingestion, indent=2), encoding="utf-8")
    print("   ingestion:", {k: ingestion[doc_id][k] for k in ("n_chunks", "embedding_prompt_tokens_provider_reported", "index_build_seconds_total")}, flush=True)
    if vs is None:
        for q in todo:
            with RAW.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": q["id"], "document": doc_id, "error": "vector store not created (see ingestion)"}) + "\n")
        continue
    nchunks = [norm(c) for c in chunks]

    # ---------------- questions (what index() does on a question)
    for q in todo:
        rec = {"id": q["id"], "document": doc_id, "question": q["question"], "question_type": q["question_type"],
               "is_answerable": q["is_answerable"], "followup_of": q.get("followup_of"),
               "history_used_by_production": False, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            compat_shims.reset_calls()
            t_start = time.perf_counter()
            with flask_app.app_context():
                t0 = time.perf_counter()
                store = chat_app.load_vector_store()
                t_load = time.perf_counter() - t0
                t0 = time.perf_counter()
                ds = store.similarity_search_with_score(q["question"])  # == production similarity_search + scores (k=4 default)
                t_search = time.perf_counter() - t0
                docs = [d for d, _ in ds]
                t0 = time.perf_counter()
                chain = chat_app.get_conversational_chain()
                t_chain_build = time.perf_counter() - t0
                t0 = time.perf_counter()
                resp = chain({"input_documents": docs, "question": q["question"]}, return_only_outputs=True)
                t_gen = time.perf_counter() - t0
            total = time.perf_counter() - t_start
            answer = resp.get("output_text", "")
            gens = [c for c in compat_shims.CALLS if c["type"] == "generation"]
            embs = [c for c in compat_shims.CALLS if c["type"] == "embedding"]
            retrieved = []
            for d, s in ds:
                n = norm(d.page_content)
                retrieved.append({"chunk_index": nchunks.index(n) if n in nchunks else None, "l2_distance": float(s),
                                  "chars": len(d.page_content)})
            ctx_chars = sum(r["chars"] for r in retrieved)
            # gold-evidence retrieval
            quotes = [(e["page"], norm(e["quote"])) for e in q["gold_evidence"]]
            found = [any(qt in norm(d.page_content) for d in docs) for _, qt in quotes]
            first_rank = None
            for rank, d in enumerate(docs, 1):
                if any(qt in norm(d.page_content) for _, qt in quotes):
                    first_rank = rank
                    break
            rec.update({
                "answer": answer, "answer_chars": len(answer), "answer_words": len(answer.split()),
                "retrieved": retrieved, "k_returned": len(docs), "context_chars": ctx_chars,
                "context_tokens_est_chars_div_4": ctx_chars // 4,
                "gold_quotes_total": len(quotes), "gold_quotes_found": sum(found),
                "gold_hit_any": any(found) if quotes else None, "gold_full": all(found) if quotes else None,
                "gold_recall": (sum(found) / len(quotes)) if quotes else None, "first_gold_rank": first_rank,
                "n_llm_calls": len(gens), "n_embedding_calls": len(embs),
                "input_tokens_provider": sum((g["prompt_tokens"] or 0) for g in gens),
                "output_tokens_provider": sum((g["output_tokens"] or 0) for g in gens),
                "done_reason": [g["done_reason"] for g in gens], "thinking_present": any(g["thinking_present"] for g in gens),
                "query_embedding_tokens_provider": sum((e["prompt_tokens"] or 0) for e in embs),
                "latency_s": {"load_vector_store": round(t_load, 4), "similarity_search_incl_query_embedding": round(t_search, 4),
                              "retrieval_total": round(t_load + t_search, 4), "chain_build": round(t_chain_build, 4),
                              "llm_chain_call": round(t_gen, 3), "llm_generation_http": round(sum(g["seconds"] for g in gens), 3),
                              "llm_prompt_eval": round(sum(g["prompt_eval_s"] for g in gens), 3),
                              "llm_decode": round(sum(g["eval_s"] for g in gens), 3), "total_pipeline": round(total, 3)},
                "prompt_chars_sent": sum(g["prompt_chars"] for g in gens),
            })
            print(f"   {q['id']}: in={rec['input_tokens_provider']} out={rec['output_tokens_provider']} "
                  f"hit={rec['gold_hit_any']} rank={first_rank} total={total:.1f}s", flush=True)
        except Exception as e:  # record the exact failure; never substitute
            rec.update({"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-1500:]})
            print(f"   {q['id']}: ERROR {type(e).__name__}: {str(e)[:200]}", flush=True)
        with RAW.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

json.dump({"shim_config": SHIM_CONFIG}, open(RES / "rag_run_config.json", "w"), indent=2)
print("finished")
