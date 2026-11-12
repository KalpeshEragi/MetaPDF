"""Shared helpers for the upgraded evaluation scripts (retrieval ablation + generation comparison)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
RES = EVAL / "results"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("METAPDF_DATA_DIR", str(RES / "_work" / "data"))

from App.rag.config import RAGConfig  # noqa: E402
from App.rag.extract import extract_pages  # noqa: E402


def squash(s: str) -> str:
    """Compare text ignoring whitespace, hyphens and punctuation. PDF extractors differ in spacing ("N= 6" vs
    "N = 6") and in hyphenation, which must not count as a retrieval miss."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def load_questions() -> list[dict]:
    return [json.loads(l) for l in (EVAL / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def load_manifest() -> dict:
    return {d["id"]: d for d in json.loads((EVAL / "corpus" / "manifest.json").read_text(encoding="utf-8"))["documents"]}


_pages_cache: dict[str, list[str]] = {}


def doc_pages(doc_id: str) -> list[str]:
    if doc_id not in _pages_cache:
        m = load_manifest()[doc_id]
        _pages_cache[doc_id] = extract_pages((EVAL / m["file"]).read_bytes())
    return _pages_cache[doc_id]


def retrieval_metrics(q: dict, chunks_text: list[str], chunk_pages: list[tuple[int, int]]) -> dict:
    quotes = [squash(e["quote"]) for e in q["gold_evidence"]]
    sq = [squash(t) for t in chunks_text]
    found = [any(qt in c for c in sq) for qt in quotes]
    first = next((r for r, c in enumerate(sq, 1) if any(qt in c for qt in quotes)), None)
    gold_pages = set(q.get("gold_pages") or [])
    page_hit = any(any(a <= p <= b for p in gold_pages) for a, b in chunk_pages) if gold_pages else None
    return {"hit": any(found) if quotes else None, "recall": sum(found) / len(quotes) if quotes else None,
            "full": all(found) if quotes else None, "mrr": (1 / first) if first else 0.0, "page_hit": page_hit}


def history_for(q: dict, by_id: dict) -> list[dict]:
    """Follow-ups get the earlier question + its GOLD answer as history (RUBRIC.md: isolates follow-up handling)."""
    if not q.get("followup_of"):
        return []
    p = by_id[q["followup_of"]]
    return [{"question": p["question"], "answer": p["gold_answer"]}]


# The configuration of the ORIGINAL chat_app.py (10k-char chunks, dense only, k=4, old prompt), re-expressed with a
# local embedder because the original Gemini embedding model no longer exists.
LEGACY = RAGConfig(chunker="legacy_chars", contextual_headers=False, retrieval_mode="dense", use_reranker=False,
                   final_k=4, history_aware_retrieval=False, prompt_style="legacy", max_output_tokens=2048,
                   temperature=0.3, history_turns=0)
UPGRADED = RAGConfig()
