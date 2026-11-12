"""Gemini client with exact token accounting, cost estimation, disk cache and rate-limit handling.

* Token counts come from Gemini's own ``usage_metadata`` (not estimates).
* Every response is cached on disk keyed by (model, system prompt, prompt, settings): re-running an evaluation or
  asking the same question about the same document again costs 0 API requests.
* 429 "per-minute" limits are waited out; a "per-day" quota error raises ``QuotaExhausted`` so callers can stop
  cleanly and resume tomorrow from the cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import logging
import time
from dataclasses import asdict, dataclass

from .config import RAGConfig, price_per_m

log = logging.getLogger("metapdf.llm")
REQUEST_TIMEOUT_MS = 60_000


class QuotaExhausted(RuntimeError):
    pass


class LLMNotConfigured(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost_usd: float | None
    latency_s: float
    cached: bool
    finish_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    p = price_per_m(model)
    if p is None:
        return None
    return round(input_tokens / 1e6 * p[0] + output_tokens / 1e6 * p[1], 8)


_client = None


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMNotConfigured("GOOGLE_API_KEY is not set (put it in env/.env)")
        from google import genai
        from google.genai import types
        # explicit timeout: without it a stalled connection can hang a request (and the whole eval) forever
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
    return _client


def _retry_delay(msg: str) -> float:
    m = re.search(r"retry[^0-9]{0,30}?(\d+(?:\.\d+)?)s", msg, re.I)
    return float(m.group(1)) + 1 if m else 20.0


def generate(prompt: str, cfg: RAGConfig, system: str | None = None, max_retries: int = 6) -> LLMResult:
    key_src = json.dumps({"m": cfg.llm_model, "s": system, "p": prompt, "t": cfg.temperature,
                          "o": cfg.max_output_tokens}, sort_keys=True)
    key = hashlib.sha256(key_src.encode()).hexdigest()
    cache_f = cfg.cache_dir / f"{key}.json"
    if cfg.llm_cache and cache_f.exists():
        d = json.loads(cache_f.read_text(encoding="utf-8"))
        d.update(cached=True, latency_s=0.0)
        return LLMResult(**d)

    from google.genai import errors, types

    client = _get_client()
    conf = types.GenerateContentConfig(temperature=cfg.temperature, max_output_tokens=cfg.max_output_tokens,
                                       system_instruction=system,
                                       automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    for attempt in range(max_retries + 1):
        t0 = time.perf_counter()
        try:
            resp = client.models.generate_content(model=cfg.llm_model, contents=prompt, config=conf)
            break
        except errors.APIError as e:
            msg = str(e)
            if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in msg:
                if re.search(r"per ?day|PerDay|daily", msg, re.I) or attempt == max_retries:
                    raise QuotaExhausted(msg[:500]) from e
                wait = _retry_delay(msg)
                log.warning("Gemini 429 rate limit, retry %d in %.0fs: %s", attempt + 1, wait, msg[:160])
                time.sleep(wait)
                continue
            if getattr(e, "code", None) in (500, 502, 503, 504) and attempt < max_retries:
                wait = min(60, 5 * 2 ** attempt)            # exponential back-off: 5, 10, 20, 40, 60, 60 s
                log.warning("Gemini %s, retry %d in %ds", getattr(e, "code", "?"), attempt + 1, wait)
                time.sleep(wait)
                continue
            raise
        except Exception as e:  # network errors / timeouts
            if attempt < max_retries and type(e).__name__ in ("ReadTimeout", "ConnectTimeout", "TimeoutException",
                                                              "ConnectError", "RemoteProtocolError", "ReadError"):
                log.warning("Gemini network error %s, retry %d", type(e).__name__, attempt + 1)
                time.sleep(5 * (attempt + 1))
                continue
            raise
    latency = time.perf_counter() - t0
    um = resp.usage_metadata
    inp = (um.prompt_token_count or 0) if um else 0
    think = (getattr(um, "thoughts_token_count", 0) or 0) if um else 0
    out = ((um.candidates_token_count or 0) if um else 0) + think       # thinking tokens are billed as output
    fr = resp.candidates[0].finish_reason if resp.candidates else None
    res = LLMResult(text=(resp.text or "").strip(), model=cfg.llm_model, input_tokens=inp, output_tokens=out,
                    thinking_tokens=think, cost_usd=estimate_cost(cfg.llm_model, inp, out),
                    latency_s=round(latency, 3), cached=False, finish_reason=str(fr) if fr else None)
    if cfg.llm_cache:
        cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(res.to_dict()), encoding="utf-8")
    return res
