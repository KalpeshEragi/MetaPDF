"""Multi-document + end-to-end baseline using the REAL production blueprint (App.chat_app.chat_app) through Flask's test client.

Requests are made exactly like the browser does: POST /chat/ with `pdf_files` (upload) and POST /chat/ with `user_question`.
Session cookie persists across requests (same client), so `vector_store_created` / `chat_history` behave as in the app.
Scenarios:
  E2E  single paper upload + one question  -> end-to-end status of the shipped route logic (with baseline-compat-v1 shims)
  S1   one request carrying 3 PDFs          -> does production index all of them? (source reading: returns after first valid file)
  S2   sequential uploads of 2 PDFs         -> global FAISS index overwritten?
For each scenario we inspect the resulting FAISS index (which paper's text it holds) and ask cross-paper + per-paper questions.
Output: eval/results/multi_document_raw.json  (final deliverable eval/multi_document_baseline.json is built from this + judgments)
"""
import io
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("GOOGLE_API_KEY", "unused-local-baseline")
os.environ.setdefault("FLASK_SECRET_KEY", "eval")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
os.chdir(ROOT)
import compat_shims  # noqa: E402

SHIM = compat_shims.install()
import App.chat_app as chat_app  # noqa: E402
from flask import Flask  # noqa: E402
import shutil  # noqa: E402

EVAL = ROOT / "eval"
WORK = EVAL / "results" / "_work_multi"
OUT = EVAL / "results" / "multi_document_raw.json"
norm = lambda s: re.sub(r"\s+", " ", s).strip()

# Fixed multi-document questions with gold answers/evidence (written before running).
MQ = [
    {"id": "md-01", "type": "comparison", "needs": ["gpt3_few_shot", "palm"],
     "question": "How do GPT-3 and PaLM compare in number of parameters and number of training tokens?",
     "gold": "GPT-3: 175B parameters, trained on 300B tokens. PaLM: 540B parameters, trained on 780B tokens.",
     "key_facts": [[r"175"], [r"\b300\b"], [r"540"], [r"780"]]},
    {"id": "md-02", "type": "cross_paper_numerical", "needs": ["gpt3_few_shot", "palm"],
     "question": "By how many billion parameters is PaLM larger than GPT-3?",
     "gold": "365 billion (540B - 175B).", "key_facts": [[r"365"]]},
    {"id": "md-03", "type": "shared_limitation", "needs": ["gpt3_few_shot", "palm"],
     "question": "Do both the GPT-3 paper and the PaLM paper discuss bias in generated text, and in which sections?",
     "gold": "Yes. GPT-3: Section 6.2 'Fairness, Bias, and Representation' (gender, race, religion). PaLM: Section 10 'Representational Bias Analysis' (distributional bias in social groups, toxicity).",
     "key_facts": [[r"\byes\b|both"], [r"6\.2|fairness"], [r"\b10\b|representational bias"]]},
    {"id": "md-04", "type": "source_attribution", "needs": ["gpt3_few_shot", "palm"],
     "question": "Which paper reports 46.2% model FLOPs utilization and which paper reports 71.2% few-shot accuracy on TriviaQA?",
     "gold": "PaLM reports 46.2% model FLOPs utilization; GPT-3 reports 71.2% few-shot TriviaQA accuracy.",
     "key_facts": [[r"palm"], [r"gpt-?3"], [r"46\.2"], [r"71\.2"]]},
    {"id": "md-05", "type": "single_paper_gpt3", "needs": ["gpt3_few_shot"],
     "question": "What accuracy did GPT-3 achieve on TriviaQA in the zero-, one- and few-shot settings?",
     "gold": "64.3% zero-shot, 68.0% one-shot, 71.2% few-shot.", "key_facts": [[r"64\.3"], [r"68\.0"], [r"71\.2"]]},
    {"id": "md-06", "type": "single_paper_palm", "needs": ["palm"],
     "question": "How many TPU v4 chips per pod did PaLM use?",
     "gold": "3072 TPU v4 chips in each of two pods.", "key_facts": [[r"3072|3,072"]]},
    {"id": "md-07", "type": "single_paper_attention", "needs": ["attention_is_all_you_need"],
     "question": "What BLEU score did the big Transformer reach on WMT 2014 English-to-German?",
     "gold": "28.4 BLEU.", "key_facts": [[r"28\.4"]]},
]
PDF = lambda d: (EVAL / "corpus" / "pdfs" / f"{d}.pdf").read_bytes()
LABEL = {"gpt3_few_shot": "GPT-3", "palm": "PaLM", "attention_is_all_you_need": "Attention"}


def new_client():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    app = Flask("metapdf_eval_e2e", root_path=str(WORK), template_folder=str(ROOT / "templates"))
    app.secret_key = "eval"
    app.register_blueprint(chat_app.chat_app)
    return app, app.test_client()


def upload(client, docs):
    data = {"pdf_files": [(io.BytesIO(PDF(d)), f"{d}.pdf") for d in docs]}
    compat_shims.reset_calls()
    t0 = time.perf_counter()
    r = client.post("/chat/", data=data, content_type="multipart/form-data")
    dt = time.perf_counter() - t0
    emb = [c for c in compat_shims.CALLS if c["type"] == "embedding"]
    return {"status_code": r.status_code, "json": r.get_json(), "seconds": round(dt, 2),
            "embedding_texts": sum(c["n_texts"] for c in emb),
            "embedding_tokens_provider": sum((c["prompt_tokens"] or 0) for c in emb)}


def inspect_index(app):
    with app.app_context():
        store = chat_app.load_vector_store()
        if store is None:
            return {"index_exists": False}
        texts = [d.page_content for d in store.docstore._dict.values()]
        tags = {"GPT-3": sum("GPT-3" in t or "Few-Shot Learners" in t for t in texts),
                "PaLM": sum("PaLM" in t for t in texts),
                "Transformer(Attention)": sum("Attention Is All You Need" in t for t in texts)}
        return {"index_exists": True, "n_chunks": store.index.ntotal, "chunks_mentioning": tags,
                "first_chunk_head": norm(texts[0])[:120]}


def ask(client, q):
    compat_shims.reset_calls()
    t0 = time.perf_counter()
    r = client.post("/chat/", data={"user_question": q["question"]})
    dt = time.perf_counter() - t0
    gens = [c for c in compat_shims.CALLS if c["type"] == "generation"]
    j = r.get_json()
    return {"id": q["id"], "type": q["type"], "question": q["question"], "needs": q["needs"], "status_code": r.status_code,
            "response": j, "seconds": round(dt, 2), "n_llm_calls": len(gens),
            "input_tokens_provider": sum((g["prompt_tokens"] or 0) for g in gens),
            "output_tokens_provider": sum((g["output_tokens"] or 0) for g in gens)}


results = {"shim_config": SHIM, "questions": MQ, "scenarios": {}}
# ---------------- E2E: single paper
app, client = new_client()
e2e = {"upload": upload(client, ["attention_is_all_you_need"])}
e2e["index"] = inspect_index(app)
e2e["ask"] = ask(client, {"id": "e2e-01", "type": "single_paper_attention", "needs": ["attention_is_all_you_need"],
                          "question": "How many identical layers make up the encoder stack of the Transformer?"})
with client.session_transaction() as s:
    e2e["session_keys"] = sorted(s.keys())
    e2e["chat_history_len"] = len(s.get("chat_history", []))
results["scenarios"]["E2E"] = e2e
print("E2E:", e2e["upload"]["json"], "|", (e2e["ask"]["response"] or {}).get("status"), flush=True)
OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")

# ---------------- S1: one request, three PDFs
app, client = new_client()
s1 = {"files_in_request": [LABEL[d] for d in ["gpt3_few_shot", "palm", "attention_is_all_you_need"]]}
s1["upload"] = upload(client, ["gpt3_few_shot", "palm", "attention_is_all_you_need"])
s1["index"] = inspect_index(app)
s1["answers"] = []
for q in MQ:
    s1["answers"].append(ask(client, q))
    print("S1", q["id"], (s1["answers"][-1]["response"] or {}).get("status"), flush=True)
    results["scenarios"]["S1_three_files_one_request"] = s1
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")

# ---------------- S2: sequential uploads GPT-3 then PaLM
app, client = new_client()
s2 = {"uploads": []}
for d in ["gpt3_few_shot", "palm"]:
    s2["uploads"].append({"file": LABEL[d], **upload(client, [d]), "index_after": inspect_index(app)})
s2["answers"] = []
for q in MQ:
    s2["answers"].append(ask(client, q))
    print("S2", q["id"], (s2["answers"][-1]["response"] or {}).get("status"), flush=True)
    results["scenarios"]["S2_sequential_uploads"] = s2
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
print("finished")
