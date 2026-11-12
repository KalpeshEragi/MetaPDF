"""RAGService: the one object the web app and the evaluation both use.

    ingest(pdf_bytes)            -> extract pages -> chunk -> embed -> save index (cached by file hash)
    ask(doc_id, question, hist)  -> retrieve (hybrid + rerank) -> prompt -> Gemini -> answer + citations + usage

Every ask() writes one JSON line to data/metrics/requests.jsonl with tokens, cost and per-stage latency.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from . import llm, prompts
from .config import RAGConfig, load_config
from .extract import extract_pages, guess_title, metadata_title, sha256
from .index import DocumentIndex
from .retrieve import retrieve

_FOLLOWUP = re.compile(r"\b(it|its|this|that|these|those|they|them|their|he|she|above|previous|same|also)\b", re.I)


class RAGService:
    def __init__(self, cfg: RAGConfig | None = None):
        self.cfg = cfg or load_config()
        self._cache: dict[str, DocumentIndex] = {}

    # ------------------------------------------------------------------ ingestion
    def _folder(self, doc_id: str) -> Path:
        sig = hashlib.sha256(json.dumps(self.cfg.index_signature(), sort_keys=True).encode()).hexdigest()[:8]
        return self.cfg.index_dir / f"{doc_id}_{sig}"     # different chunk/embedding settings never collide

    def ingest(self, pdf: bytes, filename: str = "document.pdf", title: str | None = None) -> dict:
        t0 = time.perf_counter()
        doc_id = sha256(pdf)[:32]
        idx = self.get_index(doc_id)
        if idx is not None:
            return {"doc_id": doc_id, "title": idx.title, "pages": idx.n_pages, "n_chunks": len(idx.chunks),
                    "reused_existing_index": True, "seconds": round(time.perf_counter() - t0, 3)}
        pages = extract_pages(pdf)
        t_extract = time.perf_counter() - t0
        if sum(len(p) for p in pages) < 50:
            raise ValueError("No extractable text found (the PDF may be scanned images). "
                             "Use the Summarizer, which has OCR.")
        title = title or guess_title(pages, Path(filename).stem, metadata_title(pdf))
        idx = DocumentIndex.build(doc_id, title, pages, self.cfg)
        idx.info["seconds_extract"] = round(t_extract, 3)
        idx.save(self._folder(doc_id))
        self._cache[doc_id] = idx
        return {"doc_id": doc_id, "title": title, "pages": len(pages), "n_chunks": len(idx.chunks),
                "reused_existing_index": False, "seconds": round(time.perf_counter() - t0, 3), **idx.info}

    def get_index(self, doc_id: str) -> DocumentIndex | None:
        if doc_id in self._cache:
            return self._cache[doc_id]
        idx = DocumentIndex.load(self._folder(doc_id), self.cfg)
        if idx is not None:
            self._cache[doc_id] = idx
        return idx

    # ------------------------------------------------------------------ question answering
    def retrieval_query(self, question: str, history: list[dict] | None) -> str:
        """History-aware retrieval without an extra LLM call: short follow-ups that refer back ("it", "that")
        are searched together with the previous question."""
        if self.cfg.history_aware_retrieval and history:
            if len(question.split()) <= 14 or _FOLLOWUP.search(question):
                return f"{history[-1]['question']} {question}"
        return question

    def ask(self, doc_id: str, question: str, history: list[dict] | None = None) -> dict:
        idx = self.get_index(doc_id)
        if idx is None:
            raise KeyError("Document index not found; please upload the PDF again.")
        t_start = time.perf_counter()
        history = (history or [])[-self.cfg.history_turns:] if self.cfg.history_turns else []
        rq = self.retrieval_query(question, history)
        hits, timing = retrieve(idx, rq, self.cfg, rerank_query=rq)
        t_ret = time.perf_counter() - t_start

        if self.cfg.prompt_style == "legacy":
            prompt, system = prompts.legacy_prompt(question, hits), None
        else:
            prompt, system = prompts.grounded_prompt(question, hits, history), prompts.GROUNDED_SYSTEM
        res = llm.generate(prompt, self.cfg, system=system)
        total = time.perf_counter() - t_start

        out = {
            "request_id": uuid.uuid4().hex[:12], "doc_id": doc_id, "question": question, "retrieval_query": rq,
            "answer": res.text, "abstained": prompts.NOT_FOUND.lower()[:40] in res.text.lower(),
            "citations": sorted({h.chunk.pages_label for h in hits}),
            "retrieved": [{"rank": h.rank, "chunk_id": h.chunk.id, "pages": h.chunk.pages_label,
                           "score": round(h.score, 4), "tokens": h.chunk.n_tokens, "text": h.chunk.text} for h in hits],
            "usage": {"model": res.model, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                      "thinking_tokens": res.thinking_tokens, "context_tokens": sum(h.chunk.n_tokens for h in hits),
                      "cost_usd": res.cost_usd, "cached": res.cached, "llm_calls": 0 if res.cached else 1,
                      "embedding_api_calls": 0},
            "latency_ms": {**timing, "retrieval_total": round(t_ret * 1000, 1),
                           "llm": round(res.latency_s * 1000, 1), "total": round(total * 1000, 1)},
        }
        self._log(out)
        return out

    def _log(self, rec: dict) -> None:
        try:
            self.cfg.metrics_file.parent.mkdir(parents=True, exist_ok=True)
            slim = {k: v for k, v in rec.items() if k not in ("retrieved", "answer")}
            slim["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            slim["answer_chars"] = len(rec["answer"])
            with self.cfg.metrics_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(slim) + "\n")
        except OSError:
            pass
