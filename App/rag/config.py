"""Central configuration for the RAG pipeline.

Every tunable number lives here (and can be overridden with an environment variable) so experiments and the web app
use exactly the same settings. Defaults are the configuration chosen by the evaluation in `eval/` (see
docs/RAG_UPGRADE_JOURNAL.md for the measurements behind each value).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    """Load secrets from the first .env found: $METAPDF_ENV_FILE, <repo>/env/.env, <repo>/.env."""
    candidates = [os.getenv("METAPDF_ENV_FILE"), ROOT / "env" / ".env", ROOT / ".env"]
    for c in candidates:
        if c and Path(c).is_file():
            load_dotenv(c)
            return


_load_env()


def _env(name: str, default, cast=str):
    v = os.getenv(name)
    if v is None or v == "":
        return default
    if cast is bool:
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return cast(v)


# USD per 1M tokens (input, output), standard paid tier, from https://ai.google.dev/gemini-api/docs/pricing
# (checked 2026-11-12). On the free tier the actual bill is $0; we report what the same traffic would cost on paid.
GEMINI_PRICES_PER_M = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


@dataclass(frozen=True)
class RAGConfig:
    # --- chunking
    chunker: str = "sentence"            # "sentence" (token-budgeted, page-aware) | "legacy_chars" (old 10k-char splitter)
    chunk_tokens: int = 512
    chunk_overlap_tokens: int = 64
    legacy_chunk_chars: int = 10000
    legacy_chunk_overlap: int = 1000
    contextual_headers: bool = True      # prepend "<doc title> | page N" to the text that is embedded / keyword-indexed

    # --- retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    query_instruction: str = "Represent this sentence for searching relevant passages: "
    retrieval_mode: str = "hybrid"       # "dense" | "bm25" | "hybrid"
    rrf_k: int = 60
    fetch_k: int = 30                    # candidates per retriever before fusion / rerank
    use_reranker: bool = True
    reranker_model: str = "BAAI/bge-reranker-base"
    final_k: int = 5                     # chunks passed to the LLM
    history_aware_retrieval: bool = True  # follow-ups: retrieve with previous question + current question

    # --- generation
    llm_model: str = "gemini-3.5-flash-lite"
    temperature: float = 0.2
    max_output_tokens: int = 512
    prompt_style: str = "grounded"       # "grounded" (new) | "legacy" (old 'maximum detail' prompt)
    history_turns: int = 2

    # --- infrastructure
    device: str = "auto"                 # "auto" | "cuda" | "cpu"
    data_dir: Path = field(default_factory=lambda: ROOT / "data")
    llm_cache: bool = True

    def with_(self, **kw) -> "RAGConfig":
        return replace(self, **kw)

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "rag_index"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "llm_cache"

    @property
    def metrics_file(self) -> Path:
        return self.data_dir / "metrics" / "requests.jsonl"

    def index_signature(self) -> dict:
        """Everything that changes the stored index; an index is rebuilt when this differs."""
        return {"v": 3, "chunker": self.chunker, "chunk_tokens": self.chunk_tokens,
                "chunk_overlap_tokens": self.chunk_overlap_tokens, "legacy_chunk_chars": self.legacy_chunk_chars,
                "legacy_chunk_overlap": self.legacy_chunk_overlap, "contextual_headers": self.contextual_headers,
                "embedding_model": self.embedding_model}


def load_config() -> RAGConfig:
    d = RAGConfig()
    return d.with_(
        chunk_tokens=_env("RAG_CHUNK_TOKENS", d.chunk_tokens, int),
        chunk_overlap_tokens=_env("RAG_CHUNK_OVERLAP_TOKENS", d.chunk_overlap_tokens, int),
        embedding_model=_env("RAG_EMBEDDING_MODEL", d.embedding_model),
        retrieval_mode=_env("RAG_RETRIEVAL_MODE", d.retrieval_mode),
        use_reranker=_env("RAG_USE_RERANKER", d.use_reranker, bool),
        reranker_model=_env("RAG_RERANKER_MODEL", d.reranker_model),
        final_k=_env("RAG_FINAL_K", d.final_k, int),
        llm_model=_env("RAG_LLM_MODEL", d.llm_model),
        max_output_tokens=_env("RAG_MAX_OUTPUT_TOKENS", d.max_output_tokens, int),
        device=_env("RAG_DEVICE", d.device),
        data_dir=Path(_env("METAPDF_DATA_DIR", str(d.data_dir))),
    )


def price_per_m(model: str) -> tuple[float, float] | None:
    return GEMINI_PRICES_PER_M.get(model.removeprefix("models/"))
