"""Lazy, cached loading of the local models (embedder, reranker, NLI judge).

Models load on first use and stay in memory, so the Flask app starts fast and pays the load cost once. Uses the GPU
when available (fp16 on CUDA to fit a 4 GB card), otherwise CPU.
"""
from __future__ import annotations

import threading
from functools import lru_cache

_lock = threading.Lock()


def resolve_device(device: str = "auto") -> str:
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


@lru_cache(maxsize=4)
def embedder(name: str, device: str = "auto"):
    from sentence_transformers import SentenceTransformer

    dev = resolve_device(device)
    with _lock:
        m = SentenceTransformer(name, device=dev)
        if dev == "cuda":
            m.half()
    return m


@lru_cache(maxsize=4)
def reranker(name: str, device: str = "auto"):
    from sentence_transformers import CrossEncoder

    dev = resolve_device(device)
    with _lock:
        m = CrossEncoder(name, device=dev, max_length=512)
        if dev == "cuda":
            m.model.half()
    return m


@lru_cache(maxsize=2)
def nli(name: str = "cross-encoder/nli-deberta-v3-base", device: str = "auto"):
    from sentence_transformers import CrossEncoder

    dev = resolve_device(device)
    with _lock:
        m = CrossEncoder(name, device=dev, max_length=512)
        if dev == "cuda":
            m.model.half()
    return m


def token_counter(embedding_model: str, device: str = "auto"):
    tok = embedder(embedding_model, device).tokenizer
    return lambda text: len(tok(text, add_special_tokens=False)["input_ids"])
