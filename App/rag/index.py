"""Per-document index: chunks + dense vectors (FAISS) + keyword index (BM25).

Stored under ``<data>/rag_index/<sha256-of-pdf>/`` as plain JSON + NumPy files — no pickle, so loading an index can
never execute code. Because the folder name is the file's hash, re-uploading the same PDF reuses the index (zero
re-embedding), and different users' documents never overwrite each other.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from . import models
from .chunking import Chunk, add_headers, legacy_char_chunks, sentence_chunks
from .config import RAGConfig

_STOP = set("a an the of to in on for and or is are was were be by with as at from that this these those it its "
            "what which who whom how why when where does do did can could would should has have had into than then "
            "there their they them we our you your i".split())


def bm25_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in _STOP]


class DocumentIndex:
    def __init__(self, doc_id: str, title: str, pages: int, chunks: list[Chunk], vectors: np.ndarray, info: dict):
        self.doc_id, self.title, self.n_pages, self.chunks, self.info = doc_id, title, pages, chunks, info
        self.vectors = vectors.astype(np.float32)
        self.faiss = faiss.IndexFlatIP(self.vectors.shape[1])   # cosine similarity (vectors are L2-normalised)
        self.faiss.add(self.vectors)
        self.bm25 = BM25Okapi([bm25_tokens(c.index_text) for c in chunks])

    # ---------------------------------------------------------------- build / persist
    @classmethod
    def build(cls, doc_id: str, title: str, pages: list[str], cfg: RAGConfig) -> "DocumentIndex":
        t0 = time.perf_counter()
        count = models.token_counter(cfg.embedding_model, cfg.device)
        if cfg.chunker == "legacy_chars":
            chunks = legacy_char_chunks(pages, count, cfg.legacy_chunk_chars, cfg.legacy_chunk_overlap)
        else:
            chunks = sentence_chunks(pages, count, cfg.chunk_tokens, cfg.chunk_overlap_tokens)
        if cfg.contextual_headers:
            add_headers(chunks, title)
        t_chunk = time.perf_counter() - t0
        t0 = time.perf_counter()
        emb = models.embedder(cfg.embedding_model, cfg.device)
        vecs = emb.encode([c.index_text for c in chunks], batch_size=32, normalize_embeddings=True,
                          convert_to_numpy=True, show_progress_bar=False)
        info = {"signature": cfg.index_signature(), "n_chunks": len(chunks),
                "chunk_tokens_total": sum(c.n_tokens for c in chunks), "seconds_chunking": round(t_chunk, 3),
                "seconds_embedding": round(time.perf_counter() - t0, 3), "embedding_api_calls": 0}
        return cls(doc_id, title, len(pages), chunks, np.asarray(vecs), info)

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        np.save(folder / "vectors.npy", self.vectors)
        (folder / "chunks.json").write_text(json.dumps([c.to_dict() for c in self.chunks]), encoding="utf-8")
        (folder / "meta.json").write_text(json.dumps({"doc_id": self.doc_id, "title": self.title,
                                                      "pages": self.n_pages, "info": self.info}, indent=2),
                                          encoding="utf-8")

    @classmethod
    def load(cls, folder: Path, cfg: RAGConfig) -> "DocumentIndex | None":
        meta_f = folder / "meta.json"
        if not meta_f.exists():
            return None
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        if meta["info"].get("signature") != cfg.index_signature():
            return None                                               # settings changed -> caller rebuilds
        chunks = [Chunk(**c) for c in json.loads((folder / "chunks.json").read_text(encoding="utf-8"))]
        return cls(meta["doc_id"], meta["title"], meta["pages"], chunks, np.load(folder / "vectors.npy"), meta["info"])

    # ---------------------------------------------------------------- search primitives
    def dense_search(self, qvec: np.ndarray, n: int) -> list[tuple[int, float]]:
        scores, ids = self.faiss.search(qvec.reshape(1, -1).astype(np.float32), min(n, len(self.chunks)))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]

    def bm25_search(self, query: str, n: int) -> list[tuple[int, float]]:
        scores = self.bm25.get_scores(bm25_tokens(query))
        order = np.argsort(-scores)[:n]
        return [(int(i), float(scores[i])) for i in order if scores[i] > 0]
