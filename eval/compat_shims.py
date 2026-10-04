"""baseline-compat-v1: lets the UNMODIFIED production module App/chat_app.py run in the current environment.

Why this exists (measured in eval/environment.json): the shipped code cannot run because
  1. `langchain.text_splitter`, `langchain.chains.question_answering`, `langchain.prompts` no longer exist (LangChain 1.x), and
  2. `models/embedding-001` and `models/gemini-1.5-flash-8b-001` return 404 from the Gemini API.
This file does NOT edit production code. It installs import-time substitutes into sys.modules:
  * the three legacy import paths -> the relocated, behaviour-identical LangChain classes (no logic change);
  * `langchain_google_genai.GoogleGenerativeAIEmbeddings/ChatGoogleGenerativeAI` -> local Ollama-backed classes with the
    SAME constructor call shape production uses. Per the project owner: generator = qwen3.5:4b (non-thinking), fixed embedder
    = bge-m3 (nomic-embed-text was rejected: Ollama caps it at 2048 tokens, below production's 10,000-char chunks). Production still decides chunking, k, prompt template, chain type and temperature.

Everything the fixed models need is pinned here and recorded in results so CURRENT and IMPROVED runs are comparable.
"""
import json
import sys
import time
import types
from typing import Any, List, Optional

import requests
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

OLLAMA = "http://localhost:11434"
GEN_MODEL = "qwen3.5:4b"
EMBED_MODEL = "bge-m3"
GEN_OPTIONS = {"temperature": 0.3, "num_ctx": 16384, "seed": 42, "num_predict": 4096}  # temperature mirrors production (0.3)
EMBED_NUM_CTX = 8192
EMBED_NUM_BATCH = 8192  # Ollama rejects embedding inputs larger than num_batch (default 2048) even for 8k-context models
EMBED_BATCH = 8
DOC_PREFIX, QUERY_PREFIX = "", ""  # bge-m3 needs no task prefixes (nomic-embed-text was rejected: 2048-token cap < 10k-char chunks)

CALLS: List[dict] = []  # every model call appended here by the shim classes; harness slices it per stage


def reset_calls():
    CALLS.clear()


class LocalEmbeddings(Embeddings):
    def __init__(self, model: str = "", **_: Any):  # `model` (Google id from production) is intentionally ignored
        self.model = EMBED_MODEL

    def _embed(self, texts: List[str], kind: str) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i:i + EMBED_BATCH]
            t0 = time.perf_counter()
            r = requests.post(f"{OLLAMA}/api/embed", json={
                "model": self.model, "input": batch, "truncate": False,
                "options": {"num_ctx": EMBED_NUM_CTX, "num_batch": EMBED_NUM_BATCH}}, timeout=600)
            if r.status_code != 200:
                raise RuntimeError(f"embed failed {r.status_code}: {r.text[:300]}")
            j = r.json()
            CALLS.append({"type": "embedding", "kind": kind, "n_texts": len(batch),
                          "chars": sum(len(t) for t in batch), "prompt_tokens": j.get("prompt_eval_count"),
                          "seconds": round(time.perf_counter() - t0, 4)})
            out.extend(j["embeddings"])
        return out

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed([DOC_PREFIX + t for t in texts], "documents")

    def embed_query(self, text: str) -> List[float]:
        return self._embed([QUERY_PREFIX + text], "query")[0]


class LocalChat(BaseChatModel):
    model: str = GEN_MODEL
    temperature: float = 0.3

    def __init__(self, model: str = "", temperature: float = 0.3, **kw: Any):
        super().__init__(model=GEN_MODEL, temperature=temperature)  # production's Google model id is ignored

    @property
    def _llm_type(self) -> str:
        return "ollama-local-shim"

    def _generate(self, messages, stop: Optional[List[str]] = None, run_manager=None, **kwargs: Any) -> ChatResult:
        role = {"human": "user", "ai": "assistant", "system": "system"}
        msgs = [{"role": role.get(m.type, "user"), "content": m.content} for m in messages]
        opts = dict(GEN_OPTIONS)
        opts["temperature"] = self.temperature
        t0 = time.perf_counter()
        r = requests.post(f"{OLLAMA}/api/chat", json={
            "model": self.model, "messages": msgs, "stream": False, "think": False, "options": opts}, timeout=3600)
        if r.status_code != 200:
            raise RuntimeError(f"chat failed {r.status_code}: {r.text[:300]}")
        j = r.json()
        wall = time.perf_counter() - t0
        CALLS.append({
            "type": "generation", "model": self.model, "prompt_tokens": j.get("prompt_eval_count"),
            "output_tokens": j.get("eval_count"), "done_reason": j.get("done_reason"),
            "seconds": round(wall, 3), "prompt_eval_s": round(j.get("prompt_eval_duration", 0) / 1e9, 3),
            "eval_s": round(j.get("eval_duration", 0) / 1e9, 3), "load_s": round(j.get("load_duration", 0) / 1e9, 3),
            "prompt_chars": sum(len(m["content"]) for m in msgs), "thinking_present": bool(j["message"].get("thinking")),
            "options": opts})
        msg = AIMessage(content=j["message"]["content"], usage_metadata={
            "input_tokens": j.get("prompt_eval_count") or 0, "output_tokens": j.get("eval_count") or 0,
            "total_tokens": (j.get("prompt_eval_count") or 0) + (j.get("eval_count") or 0)})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def install():
    """Install aliases into sys.modules. Call BEFORE importing App.chat_app."""
    import langchain_classic.chains.question_answering as classic_qa
    import langchain_core.prompts as core_prompts
    import langchain_text_splitters as splitters

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    mod("langchain.text_splitter", RecursiveCharacterTextSplitter=splitters.RecursiveCharacterTextSplitter)
    mod("langchain.chains", question_answering=classic_qa)
    sys.modules["langchain.chains.question_answering"] = classic_qa
    mod("langchain.prompts", PromptTemplate=core_prompts.PromptTemplate)
    mod("langchain_google_genai", GoogleGenerativeAIEmbeddings=LocalEmbeddings, ChatGoogleGenerativeAI=LocalChat)
    return {
        "legacy_aliases": {"langchain.text_splitter": "langchain_text_splitters",
                           "langchain.chains.question_answering": "langchain_classic.chains.question_answering",
                           "langchain.prompts": "langchain_core.prompts"},
        "generator": {"model": GEN_MODEL, "mode": "non-thinking (think=false)", "options": GEN_OPTIONS},
        "embedder": {"model": EMBED_MODEL, "num_ctx": EMBED_NUM_CTX, "num_batch": EMBED_NUM_BATCH, "truncate": False, "prefixes": [DOC_PREFIX, QUERY_PREFIX],
                     "batch_size": EMBED_BATCH},
    }
