"""Retrieval: dense, BM25, hybrid (Reciprocal Rank Fusion), optional cross-encoder reranking.

Pipeline for the default config:  question ─┬─ dense top-30 ─┐
                                            └─ BM25  top-30 ─┴─ RRF fuse ─ rerank (cross-encoder) ─ keep top-5
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import models
from .chunking import Chunk
from .config import RAGConfig
from .index import DocumentIndex


@dataclass
class Retrieved:
    chunk: Chunk
    score: float
    rank: int


def rrf(rank_lists: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank_in_list(d))."""
    scores: dict[int, float] = {}
    for lst in rank_lists:
        for r, cid in enumerate(lst, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r)
    return sorted(scores, key=lambda c: -scores[c])


def retrieve(index: DocumentIndex, query: str, cfg: RAGConfig, rerank_query: str | None = None
             ) -> tuple[list[Retrieved], dict]:
    t = {}
    t0 = time.perf_counter()
    cand: list[int]
    if cfg.retrieval_mode in ("dense", "hybrid"):
        emb = models.embedder(cfg.embedding_model, cfg.device)
        qv = emb.encode([cfg.query_instruction + query], normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False)[0]
        dense = [i for i, _ in index.dense_search(qv, cfg.fetch_k)]
    t["dense_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter()
    if cfg.retrieval_mode in ("bm25", "hybrid"):
        sparse = [i for i, _ in index.bm25_search(query, cfg.fetch_k)]
    t["bm25_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    if cfg.retrieval_mode == "dense":
        cand = dense
    elif cfg.retrieval_mode == "bm25":
        cand = sparse
    else:
        cand = rrf([dense, sparse], cfg.rrf_k)[: cfg.fetch_k]

    t0 = time.perf_counter()
    if cfg.use_reranker and cand:
        ce = models.reranker(cfg.reranker_model, cfg.device)
        q = rerank_query or query
        scores = ce.predict([(q, index.chunks[i].text) for i in cand], batch_size=16, show_progress_bar=False)
        ranked = sorted(zip(cand, (float(s) for s in scores)), key=lambda x: -x[1])
    else:
        ranked = [(i, 1.0 / r) for r, i in enumerate(cand, 1)]
    t["rerank_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out = [Retrieved(index.chunks[i], s, r) for r, (i, s) in enumerate(ranked[: cfg.final_k], 1)]
    return out, t
