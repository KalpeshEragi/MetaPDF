"""Offline retrieval ablation — zero LLM calls.

For each configuration, index the 5 papers and run the 35 answerable questions, then score whether the gold evidence
quotes were retrieved (Hit@k, Recall@k, Full-evidence, MRR, page-hit) and how many context tokens would be sent to the
LLM. Each row changes ONE thing relative to the row before it, so the table reads as "what did this technique add".

Run:  <venv>/python eval/run_retrieval_ablation.py
Out:  eval/results/retrieval_ablation.json, eval/results/retrieval_ablation.md
"""
from __future__ import annotations

import json
import statistics
import time

from rag_common import LEGACY, RES, UPGRADED, doc_pages, history_for, load_manifest, load_questions, retrieval_metrics

from App.rag.index import DocumentIndex
from App.rag.models import resolve_device
from App.rag.pipeline import RAGService
from App.rag.retrieve import retrieve

S = dict(chunker="sentence", chunk_tokens=512, chunk_overlap_tokens=64, contextual_headers=False, final_k=5)
CONFIGS = [
    # name, config, what changed
    ("A. Original design (10k-char chunks, dense, k=4)", LEGACY, "baseline"),
    ("B. Token chunks (512 tok, sentence-aligned, dense, k=5)", LEGACY.with_(**S), "chunking"),
    ("C. + contextual headers", LEGACY.with_(**{**S, "contextual_headers": True}), "headers"),
    ("D. BM25 keyword only", LEGACY.with_(**{**S, "contextual_headers": True, "retrieval_mode": "bm25"}), "bm25"),
    ("E. Hybrid dense+BM25 (RRF)", LEGACY.with_(**{**S, "contextual_headers": True, "retrieval_mode": "hybrid"}), "hybrid"),
    ("F. + cross-encoder reranker", LEGACY.with_(**{**S, "contextual_headers": True, "retrieval_mode": "hybrid",
                                                    "use_reranker": True}), "rerank"),
    ("G. + history-aware follow-ups (= UPGRADED default)", UPGRADED, "history"),
    # sweeps around the default
    ("sweep: chunk 192 tok", UPGRADED.with_(chunk_tokens=192, chunk_overlap_tokens=32), "sweep"),
    ("sweep: chunk 320 tok", UPGRADED.with_(chunk_tokens=320, chunk_overlap_tokens=48), "sweep"),
    ("sweep: final k=3", UPGRADED.with_(final_k=3), "sweep"),
    ("sweep: final k=8", UPGRADED.with_(final_k=8), "sweep"),
    ("sweep: dense + rerank (no BM25)", UPGRADED.with_(retrieval_mode="dense"), "sweep"),
    ("sweep: embedder bge-small", UPGRADED.with_(embedding_model="BAAI/bge-small-en-v1.5"), "sweep"),
    ("sweep: embedder all-MiniLM-L6-v2", UPGRADED.with_(embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                                                        query_instruction=""), "sweep"),
]


def main():
    qs = load_questions()
    by_id = {q["id"]: q for q in qs}
    answerable = [q for q in qs if q["is_answerable"]]
    manifest = load_manifest()
    idx_cache: dict[tuple, DocumentIndex] = {}
    rows, per_q = [], {}
    print("device:", resolve_device(), flush=True)
    for name, cfg, tag in CONFIGS:
        t_cfg = time.perf_counter()
        svc = RAGService(cfg)
        recs = []
        for q in answerable:
            key = (q["document"], json.dumps(cfg.index_signature(), sort_keys=True))
            if key not in idx_cache:
                idx_cache[key] = DocumentIndex.build(q["document"], manifest[q["document"]]["title"],
                                                     doc_pages(q["document"]), cfg)
            idx = idx_cache[key]
            rq = svc.retrieval_query(q["question"], history_for(q, by_id))
            t0 = time.perf_counter()
            hits, _ = retrieve(idx, rq, cfg, rerank_query=rq)
            ms = (time.perf_counter() - t0) * 1000
            m = retrieval_metrics(q, [h.chunk.text for h in hits], [(h.chunk.page_start, h.chunk.page_end) for h in hits])
            m.update(id=q["id"], type=q["question_type"], ctx_tokens=sum(h.chunk.n_tokens for h in hits), ms=ms)
            recs.append(m)
        mean = lambda k: round(statistics.mean(float(r[k]) for r in recs if r[k] is not None), 4)
        row = {"config": name, "tag": tag, "n": len(recs), "hit": mean("hit"), "recall": mean("recall"),
               "full": mean("full"), "mrr": mean("mrr"), "page_hit": mean("page_hit"),
               "ctx_tokens_mean": round(statistics.mean(r["ctx_tokens"] for r in recs)),
               "retrieval_ms_p50": round(statistics.median(r["ms"] for r in recs), 1),
               "followup_hit": mean_sub(recs, "hit", lambda r: r["type"] == "follow_up"),
               "settings": {k: v for k, v in cfg.__dict__.items() if k not in ("data_dir",)}}
        rows.append(row)
        per_q[name] = recs
        print(f"{name:55s} hit={row['hit']:.3f} recall={row['recall']:.3f} full={row['full']:.3f} "
              f"mrr={row['mrr']:.3f} ctx={row['ctx_tokens_mean']} ({time.perf_counter() - t_cfg:.0f}s)", flush=True)

    (RES / "retrieval_ablation.json").write_text(json.dumps({"device": resolve_device(), "rows": rows,
                                                             "per_question": per_q}, indent=1, default=str),
                                                 encoding="utf-8")
    lines = ["| Configuration | Hit@k | Recall@k | All evidence | MRR | Gold page hit | Follow-up hit | Context tokens | Retrieval p50 ms |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['config']} | {r['hit']:.3f} | {r['recall']:.3f} | {r['full']:.3f} | {r['mrr']:.3f} | "
                     f"{r['page_hit']:.3f} | {r['followup_hit']:.2f} | {r['ctx_tokens_mean']:,} | {r['retrieval_ms_p50']} |")
    (RES / "retrieval_ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def mean_sub(recs, k, pred):
    v = [float(r[k]) for r in recs if pred(r) and r[k] is not None]
    return round(statistics.mean(v), 4) if v else 0.0


if __name__ == "__main__":
    main()
