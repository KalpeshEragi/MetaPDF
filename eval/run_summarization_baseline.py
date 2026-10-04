"""Baseline summarization benchmark: executes the UNMODIFIED production functions from App/streamlit_app/stream_app.py.

stream_app.py is a Streamlit script (UI code at import), so the five logic functions (load_model, extract_pages,
preprocess_text, generate_smart_summary + TYPING_SPEED) are extracted with `ast` and exec'd verbatim into a namespace that
has a stub `st` (decorators/UI calls are recorded, not rendered). The page loop below replicates the script's
"Generate Smart Summaries" loop (Balanced slider = max 150 / min 50, "all pages", metrics off) with the same conditions.
The BART pipeline is wrapped by a delegating proxy ONLY to count calls/tokens/time; its outputs are untouched.

Run: <project>/venv/Scripts/python.exe eval/run_summarization_baseline.py [--docs id ...]
Output: eval/results/summarization_baseline_raw.json (per paper) + per-paper summaries (gitignored text in _work/).
"""
import argparse
import ast
import io
import json
import os
import re
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
RES = EVAL / "results"
SRC = ROOT / "App" / "streamlit_app" / "stream_app.py"
os.environ["HF_HUB_OFFLINE"] = "1"  # weights were downloaded once with approval; never fetch during runs
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--docs", nargs="*", default=["attention_is_all_you_need", "rag_lewis", "constitutional_ai"])
args = ap.parse_args()

# ---------------------------------------------------------------- stub streamlit
LOG = []


class _Quiet:
    def __getattr__(self, name):
        return lambda *a, **k: LOG.append((name, str(a)[:200]))


st = types.SimpleNamespace(
    cache_resource=lambda f: f, sidebar=_Quiet(),
    error=lambda m: LOG.append(("error", str(m)[:300])), warning=lambda m: LOG.append(("warning", str(m)[:300])),
    info=lambda m: LOG.append(("info", str(m)[:300])), success=lambda m: LOG.append(("success", str(m)[:300])),
)
import PyPDF2  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline  # noqa: E402

ns = {"st": st, "pipeline": pipeline, "AutoTokenizer": AutoTokenizer, "AutoModelForSeq2SeqLM": AutoModelForSeq2SeqLM,
      "PyPDF2": PyPDF2, "torch": torch, "re": re, "time": time, "__file__": str(SRC), "__name__": "stream_app_extracted"}
import html as _html  # noqa: E402
ns["html"] = _html
source = SRC.read_text(encoding="utf-8")
tree = ast.parse(source)
WANT = {"load_model", "extract_pages", "preprocess_text", "generate_smart_summary"}
taken = []
for node in tree.body:
    if (isinstance(node, ast.FunctionDef) and node.name in WANT) or (
            isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TYPING_SPEED" for t in node.targets)):
        code = compile(ast.Module(body=[node], type_ignores=[]), str(SRC), "exec")
        exec(code, ns)
        taken.append(getattr(node, "name", "TYPING_SPEED"))
assert WANT <= set(taken), taken
real_load_model = ns["load_model"]


# ---------------------------------------------------------------- as-shipped status, then baseline-compat-v1 shim
SHIPPED = {}
LOG.clear()
_shipped = real_load_model()  # production load_model with the REAL transformers.pipeline
SHIPPED["load_model_returned_none"] = _shipped is None
SHIPPED["ui_messages"] = [m for m in LOG if m[0] in ("error", "warning")]
print("AS-SHIPPED load_model ->", "None (FAILED)" if _shipped is None else "pipeline ok", SHIPPED["ui_messages"][:1], flush=True)
SHIPPED["generate_smart_summary_output_as_shipped"] = repr(ns["generate_smart_summary"]("This is a sentence about transformers. " * 30, 150, 50))


class CompatSummarizationPipeline:
    """Equivalent of the removed transformers `summarization` pipeline: tokenize (no truncation, the old default),
    model.generate(**same kwargs), decode (skip special tokens, no clean-up) -> [{'summary_text': ...}]."""

    def __init__(self, model, tokenizer):
        self.model, self.tokenizer = model, tokenizer

    def __call__(self, text, **gen_kwargs):
        enc = self.tokenizer(text, return_tensors="pt", truncation=False)
        enc = {k: v.to(self.model.device) for k, v in enc.items()}
        with torch.no_grad():
            ids = self.model.generate(**enc, **gen_kwargs)
        return [{"summary_text": self.tokenizer.decode(ids[0], skip_special_tokens=True, clean_up_tokenization_spaces=False)}]


def _compat_pipeline(task, model=None, tokenizer=None, **kw):
    assert task == "summarization"
    return CompatSummarizationPipeline(model, tokenizer)


ns["pipeline"] = _compat_pipeline  # only the removed pipeline() entry point is substituted; load_model itself is production code
LOG.clear()
real_load_model = ns["load_model"]

# ---------------------------------------------------------------- measuring proxy (delegates; does not alter outputs)
class Proxy:
    def __init__(self, real):
        self.real, self.calls = real, []

    def __call__(self, text, **kw):
        tok = self.real.tokenizer
        t0 = time.perf_counter()
        out = self.real(text, **kw)
        dt = time.perf_counter() - t0
        summ = out[0]["summary_text"]
        self.calls.append({"in_tokens": len(tok.encode(text)), "out_tokens": len(tok.encode(summ, add_special_tokens=False)),
                           "seconds": round(dt, 3), "kwargs": sorted(kw), "second_pass": "num_beams" not in kw,
                           "in_words": len(text.split()), "out_words": len(summ.split())})
        return out


t0 = time.perf_counter()
proxy = Proxy(real_load_model())
model_load_seconds = round(time.perf_counter() - t0, 2)
ns["load_model"] = lambda: proxy  # generate_smart_summary looks up load_model() in this namespace
device = "cuda" if torch.cuda.is_available() else "cpu"
print("model loaded in", model_load_seconds, "s on", device, "| st log:", LOG[:3], flush=True)

manifest = {d["id"]: d for d in json.loads((EVAL / "corpus" / "manifest.json").read_text(encoding="utf-8"))["documents"]}
out_path = RES / "summarization_baseline_raw.json"
results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
results["_as_shipped"] = SHIPPED
results["_compat"] = {"name": "baseline-compat-v1", "substitution": "transformers.pipeline('summarization') -> direct model.generate equivalent (task removed in transformers 5.x)",
                      "transformers_version": __import__("transformers").__version__, "device": device}
(RES / "_work").mkdir(exist_ok=True)

MAXL, MINL = 150, 50  # "Balanced" - the slider default in the production UI
for doc_id in args.docs:
    if doc_id in results:
        print("skip (done):", doc_id)
        continue
    meta = manifest[doc_id]
    pdf = (EVAL / meta["file"]).read_bytes()
    print(f"=== {doc_id} ({meta['pages']} pages)", flush=True)
    LOG.clear()
    # repeated-interaction behaviour: how long does production extract_pages take, run 3x on the same file (no caching)?
    ext_times, pages = [], None
    for _ in range(3):
        t0 = time.perf_counter()
        pages = ns["extract_pages"](io.BytesIO(pdf))
        ext_times.append(round(time.perf_counter() - t0, 3))
    ext_log = list(LOG)
    page_recs, combined = [], ""
    t_all = time.perf_counter()
    for i, page_text in enumerate(pages, 1):
        calls_before = len(proxy.calls)
        chunks = ns["preprocess_text"](page_text) if page_text else []
        rec = {"page": i, "source_words": len(page_text.split()), "n_chunks": len(chunks), "summarized": False}
        if page_text and len(page_text.strip()) > 20:  # same condition as the UI loop
            t0 = time.perf_counter()
            summary = ns["generate_smart_summary"](page_text, MAXL, MINL)
            dt = time.perf_counter() - t0
            new = proxy.calls[calls_before:]
            rec.update({"summarized": True, "summary": summary, "summary_words": len(summary.split()),
                        "bart_calls": len(new), "second_pass_calls": sum(c["second_pass"] for c in new),
                        "in_tokens": sum(c["in_tokens"] for c in new), "out_tokens": sum(c["out_tokens"] for c in new),
                        "seconds": round(dt, 3), "call_detail": new})
            combined += summary + " "
        page_recs.append(rec)
        print(f"   p{i}: chunks={rec['n_chunks']} calls={rec.get('bart_calls')} 2nd={rec.get('second_pass_calls')} "
              f"{rec.get('seconds')}s", flush=True)
    total_s = round(time.perf_counter() - t_all, 2)
    s = [r for r in page_recs if r["summarized"]]
    src_words = sum(len(p.split()) for p in pages)
    results[doc_id] = {
        "title": meta["title"], "pages": meta["pages"], "device": device, "model_load_seconds": model_load_seconds,
        "extract_pages_seconds_3_runs_uncached": ext_times, "extract_pages_ui_messages": ext_log,
        "pages_summarized": len(s), "total_chunks": sum(r["n_chunks"] for r in page_recs),
        "bart_calls": sum(r["bart_calls"] for r in s), "second_pass_calls": sum(r["second_pass_calls"] for r in s),
        "in_tokens": sum(r["in_tokens"] for r in s), "out_tokens": sum(r["out_tokens"] for r in s),
        "summarization_seconds": total_s, "seconds_per_page_mean": round(total_s / max(1, len(s)), 2),
        "source_words": src_words, "per_page_summary_words": sum(r["summary_words"] for r in s),
        "combined_summary_words": len(combined.split()), "combined_summary_is_concatenation": True,
        "compression_ratio_summary_over_source_words": round(len(combined.split()) / max(1, src_words), 3),
        "page_records": page_recs, "combined_summary": combined.strip(),
    }
    out_path.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"   -> {doc_id}: {results[doc_id]['bart_calls']} BART calls, {total_s}s, combined {results[doc_id]['combined_summary_words']} words "
          f"({results[doc_id]['compression_ratio_summary_over_source_words']:.0%} of source)", flush=True)
print("finished")
