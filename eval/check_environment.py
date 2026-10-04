"""Baseline environment verification for MetaPDF (read-only w.r.t. production code).

Run with the project's own interpreter, from the repo root:
    <project>/venv/Scripts/python.exe eval/check_environment.py

Writes eval/environment.json. Never prints or stores secret values: only whether a key is
present. Every check records the exact exception on failure instead of substituting a
different component.
"""
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "environment.json"
# The project's real secrets live in the main checkout (gitignored). Values are loaded into
# the process environment only; they are never written anywhere.
ENV_FILE = Path(os.environ.get("METAPDF_ENV_FILE", r"C:\AllImpprojects\MetaPDF\env\.env"))

report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": {}}


def check(name):
    def deco(fn):
        t0 = time.time()
        try:
            res = fn()
            report["checks"][name] = {"status": "ok", "seconds": round(time.time() - t0, 2), **(res or {})}
        except Exception as e:  # record the exact failure, do not mask it
            report["checks"][name] = {
                "status": "FAILED",
                "seconds": round(time.time() - t0, 2),
                "error_type": type(e).__name__,
                "error": str(e)[:600],
            }
        return fn
    return deco


@check("python")
def _():
    return {"version": sys.version, "executable": sys.executable, "platform": platform.platform()}


@check("hardware")
def _():
    info = {"cpu_count_logical": os.cpu_count(), "processor": platform.processor()}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception as e:
        info["ram_error"] = str(e)
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20)
        info["gpu"] = out.stdout.strip() or out.stderr.strip()
    except Exception as e:
        info["gpu_error"] = str(e)
    try:
        import torch
        info["torch"] = torch.__version__
        info["torch_cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["torch_cuda_device"] = torch.cuda.get_device_name(0)
    except Exception as e:
        info["torch_error"] = str(e)
    return info


@check("packages")
def _():
    from importlib import metadata
    names = ["flask", "flask-cors", "langchain", "langchain-classic", "langchain-core", "langchain-community",
             "langchain-google-genai", "langchain-text-splitters", "google-generativeai", "google-genai",
             "faiss-cpu", "PyPDF2", "pypdf", "streamlit", "torch", "transformers", "easyocr", "pdf2image",
             "Pillow", "numpy", "python-dotenv", "chromadb", "pywin32", "comtypes", "psutil", "reportlab"]
    versions = {}
    for n in names:
        try:
            versions[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            versions[n] = None
    return {"versions": versions}


@check("secrets_presence")
def _():
    present = {}
    if ENV_FILE.exists():
        from dotenv import dotenv_values
        vals = dotenv_values(ENV_FILE)
        for k, v in vals.items():
            if v:
                os.environ.setdefault(k, v)
        present["env_file_found"] = True
        present["keys_present"] = sorted(k for k, v in vals.items() if v)
    else:
        present["env_file_found"] = False
    return present


@check("legacy_imports_as_used_by_production")
def _():
    # Exactly the import statements at the top of App/chat_app.py
    results = {}
    for mod in ["langchain.text_splitter", "langchain.chains.question_answering", "langchain.prompts",
                "langchain_community.vectorstores", "langchain_google_genai", "google.generativeai", "PyPDF2",
                "faiss"]:
        try:
            importlib.import_module(mod)
            results[mod] = "ok"
        except Exception as e:
            results[mod] = f"FAILED: {type(e).__name__}: {e}"
    sys.path.insert(0, str(ROOT))
    try:
        importlib.import_module("App.chat_app")
        results["App.chat_app (production module)"] = "ok"
    except Exception as e:
        results["App.chat_app (production module)"] = f"FAILED: {type(e).__name__}: {e}"
    return {"imports": results}


@check("relocated_equivalents_available")
def _():
    # Where the removed legacy symbols live in the installed LangChain (informational only).
    out = {}
    for mod, attr in [("langchain_text_splitters", "RecursiveCharacterTextSplitter"),
                      ("langchain_classic.chains.question_answering", "load_qa_chain"),
                      ("langchain_core.prompts", "PromptTemplate")]:
        try:
            out[f"{mod}.{attr}"] = hasattr(importlib.import_module(mod), attr)
        except Exception as e:
            out[f"{mod}.{attr}"] = f"FAILED: {type(e).__name__}: {e}"
    try:
        import inspect
        from langchain_community.vectorstores import FAISS
        out["FAISS.similarity_search default k"] = inspect.signature(FAISS.similarity_search).parameters["k"].default
    except Exception as e:
        out["FAISS.similarity_search default k"] = f"FAILED: {e}"
    return {"relocated": out}


@check("gemini_model_listing")
def _():
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    wanted = {"models/gemini-1.5-flash-8b-001": None, "models/embedding-001": None}
    all_models = []
    for m in genai.list_models():
        all_models.append(m.name)
        if m.name in wanted:
            wanted[m.name] = list(m.supported_generation_methods)
    flash = sorted(n for n in all_models if "flash" in n)[:25]
    emb = sorted(n for n in all_models if "embed" in n)
    return {"configured_models_listed": wanted, "listed_embedding_models": emb, "sample_flash_models": flash,
            "total_models_listed": len(all_models)}


@check("gemini_embedding_live_call")
def _():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    e = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    t0 = time.time()
    v = e.embed_query("baseline ping")
    return {"dimension": len(v), "latency_s": round(time.time() - t0, 3)}


@check("gemini_generation_live_call")
def _():
    from langchain_google_genai import ChatGoogleGenerativeAI
    m = ChatGoogleGenerativeAI(model="models/gemini-1.5-flash-8b-001", temperature=0.3)
    t0 = time.time()
    r = m.invoke("Reply with the single word: OK")
    return {"latency_s": round(time.time() - t0, 3), "usage_metadata": getattr(r, "usage_metadata", None),
            "reply_head": str(r.content)[:40]}


@check("bart_summarizer")
def _():
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    hit = sorted(p.name for p in cache.glob("models--facebook--bart-large-cnn*")) if cache.exists() else []
    res = {"hf_cache_dir": str(cache), "bart_in_local_cache": hit}
    if not hit:
        res["note"] = "weights not cached; not downloading during environment check (needs approval)"
        return res
    os.environ["HF_HUB_OFFLINE"] = "1"
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline
    import torch
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained("facebook/bart-large-cnn")
    model = AutoModelForSeq2SeqLM.from_pretrained("facebook/bart-large-cnn")
    if torch.cuda.is_available():
        model = model.half().to("cuda")
    res["device"] = "cuda" if torch.cuda.is_available() else "cpu"
    res["load_seconds"] = round(time.time() - t0, 1)
    try:
        s = pipeline("summarization", model=model, tokenizer=tok)
        out = s("The quick brown fox jumps over the lazy dog. " * 20, max_length=40, min_length=10,
                do_sample=False, num_beams=4)
        res["pipeline_summarization_task"] = "ok"
        res["sample_output_head"] = out[0]["summary_text"][:80]
    except Exception as e:
        res["pipeline_summarization_task"] = f"FAILED: {type(e).__name__}: {str(e)[:300]}"
    return res


@check("ocr")
def _():
    res = {}
    try:
        import easyocr  # noqa: F401
        res["easyocr_import"] = "ok"
    except Exception as e:
        res["easyocr_import"] = f"FAILED: {type(e).__name__}: {e}"
    res["poppler_pdftoppm_on_path"] = shutil.which("pdftoppm")
    easy = Path.home() / ".EasyOCR" / "model"
    res["easyocr_models_cached"] = sorted(p.name for p in easy.glob("*")) if easy.exists() else []
    try:
        from pdf2image import convert_from_bytes
        # smallest valid PDF
        pdf = (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 50 50]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
        convert_from_bytes(pdf, dpi=50)
        res["pdf2image_rasterize"] = "ok"
    except Exception as e:
        res["pdf2image_rasterize"] = f"FAILED: {type(e).__name__}: {str(e)[:300]}"
    return res


@check("streamlit")
def _():
    import streamlit
    return {"version": streamlit.__version__}


OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
for k, v in report["checks"].items():
    print(f"{k:45s} {v['status']}")
