# 📑 MetaPDF: Chat with PDFs using an evaluated RAG pipeline

MetaPDF is a Flask web app with three tools:

1. **Chat with a PDF.** A retrieval-augmented generation (RAG) pipeline with hybrid search, a reranker, page
   citations and a hallucination check, plus token and cost accounting.
2. **Summarize a PDF** with a local BART model (Streamlit), with OCR for scanned pages.
3. **Convert** DOCX, PPTX, XLSX and TXT files to PDF.

What makes this project different from a tutorial RAG app is that **every design choice is measured**. A fixed
evaluation set of 5 research papers and 40 questions with gold evidence quotes scores retrieval quality, answer
quality, hallucination rate, tokens, cost and latency for the original design and the upgraded one.

> 📘 **Want the full story?** [`docs/RAG_UPGRADE_JOURNAL.md`](docs/RAG_UPGRADE_JOURNAL.md) explains every decision,
> experiment, mistake and fix step by step, written for a student.

---

## 📊 Results: original design vs upgraded

### Retrieval (offline, 35 answerable questions, no LLM calls)
Each row adds one technique to the row above it ([full table](eval/results/retrieval_ablation.md)).

| Configuration | Evidence hit@k | Recall@k | MRR | Context tokens / question |
|---|---|---|---|---|
| Original: 10k-char chunks, dense only, k=4 | 0.714 | 0.648 | 0.488 | 9,454 |
| + 512-token sentence chunks with page metadata | 0.714 | 0.635 | 0.553 | 2,384 |
| + contextual headers (title, page) | 0.829 | 0.764 | 0.587 | 2,401 |
| + hybrid BM25 + dense (Reciprocal Rank Fusion) | 0.886 | 0.778 | 0.652 | 2,410 |
| + cross-encoder reranker | 0.914 | 0.835 | 0.754 | 2,408 |
| **+ history-aware follow-ups (final)** | **0.943** | **0.864** | **0.780** | **2,409** |

### End-to-end answers with Gemini (40 questions, same LLM for both)

| Metric | Original | Upgraded |
|---|---|---|
| Answers containing an unsupported (hallucinated) claim | 50.0% | **14.3%** |
| Groundedness (answer sentences supported by the excerpts) | 0.82 | **0.92** |
| Unanswerable questions, rubric score 0–2 | 1.0 | **2.0** |
| False "not in the document" on answerable questions | 9 / 35 | **1 / 35** |
| Key-fact coverage | 77.7% | **81.7%** |
| Input tokens per question | 10,525 | **2,751 (−74%)** |
| Output tokens per answer | 292 | **65 (−78%)** |
| Cost per 1,000 questions (paid-tier price) | $3.89 | **$0.99 (−75%)** |
| Gemini latency p50 | 20.5 s | **7.4 s** |

The original prompt told the model to fall back on "relevant knowledge", so on unanswerable questions it refused and
then answered from memory anyway. The upgraded system refuses cleanly and cites pages for everything it states.

*Hallucination is scored by a local NLI model (DeBERTa-v3 ensemble, sentence-level premises) that checks every
answer sentence against the retrieved excerpts, so the generator never grades itself. Completeness checks the question's key facts. See
[`eval/RUBRIC.md`](eval/RUBRIC.md) and the journal for method and caveats (35–40 questions means about ±3 points per question).*

---

## 🧠 RAG architecture

```
                 ┌──────────────── ingestion (once per PDF, cached by SHA-256) ─────────────────┐
  PDF ─► pypdf (per page) ─► sentence-aligned 512-token chunks + page numbers + "title | page" header
                 └─► bge-small embeddings (local GPU) ─► FAISS      └─► BM25 keyword index
                 └──────────────────────────────────────────────────────────────────────────────┘

  question ─► (follow-up? + previous question) ─┬─► dense top-30 ─┐
                                                 └─► BM25  top-30 ─┴─► RRF fusion ─► bge-reranker ─► top-5
  top-5 excerpts + grounded prompt ("only these excerpts, cite pages, say when not found")
            ─► Gemini 3.5 Flash-Lite ─► answer with [p. N] citations
            ─► metrics log: exact tokens (usage_metadata), $ cost, latency per stage
```

| Component | Choice | Why |
|---|---|---|
| Embeddings | `BAAI/bge-small-en-v1.5`, local | 0 API calls to index; with BM25 + reranker it scores the same as bge-base (3× larger) and MiniLM on this eval |
| Keyword search | BM25 (`rank_bm25`) | exact tokens (`WMT 2014`, `P100`, `540B`) that embeddings miss; on this corpus BM25 alone beat dense alone, and removing it from the final system lowers MRR 0.78 → 0.72 |
| Fusion | Reciprocal Rank Fusion (k=60) | merges rankings without calibrating scores |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | biggest MRR gain (0.65 → 0.75) for ~380 ms on a laptop GPU |
| LLM | `gemini-3.5-flash-lite` | only the final answer uses the API, and responses are disk-cached |
| Hallucination check | NLI ensemble (`nli-deberta-v3` base + small) | offline, free, independent of the generator; checked on hand-made true and false claims first |
| Storage | per-document folder `data/rag_index/<sha256>_<settings-hash>/` with JSON and NumPy | no pickle; re-uploading a file costs 0; users never overwrite each other |

All settings are in [`App/rag/config.py`](App/rag/config.py) and can be overridden with environment variables
(see [`.env.example`](.env.example)).

---

## 🚀 Quick start

```bash
git clone https://github.com/KalpeshEragi/MetaPDF.git
cd MetaPDF
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on Linux/macOS)
```

Optional, for GPU (NVIDIA): install the CUDA build of PyTorch first.

```bash
pip install torch==2.13.0+cu126 torchvision==0.28.0+cu126 --index-url https://download.pytorch.org/whl/cu126
```

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `env/.env`, then set `GOOGLE_API_KEY` (free key from Google AI Studio) and `FLASK_SECRET_KEY`.

```bash
python app.py
```

Open http://localhost:5000/chat. The first upload downloads the local models (about 0.5 GB) once.

For the summarizer, run this in a second terminal:

```bash
streamlit run App/streamlit_app/stream_app.py
```

### Run the tests and the evaluation

Unit tests (no network, no GPU):

```bash
python -m pytest tests -q
```

Retrieval ablation (no API calls, about 3 minutes on GPU):

```bash
python eval/run_retrieval_ablation.py
```

Before/after answers (about 80 Gemini calls, cached and resumable):

```bash
python eval/run_generation_eval.py
```

The evaluation PDFs are public arXiv papers kept out of git. Download them with the URLs in
[`eval/corpus/manifest.json`](eval/corpus/manifest.json) into `eval/corpus/pdfs/`.

---

## 📁 Project structure

```
App/
├── rag/                  ← the RAG pipeline (used by both the web app and the evaluation)
│   ├── config.py         all settings + Gemini price table
│   ├── extract.py        PDF → per-page text (pypdf)
│   ├── chunking.py       sentence-aligned token chunks with page ranges (+ legacy chunker for comparison)
│   ├── index.py          FAISS + BM25 per document, safe JSON/NumPy persistence
│   ├── retrieve.py       dense / BM25 / hybrid RRF / cross-encoder rerank
│   ├── prompts.py        grounded prompt with citations (+ original prompt for comparison)
│   ├── llm.py            Gemini client: exact tokens, cost, cache, rate-limit handling
│   ├── faithfulness.py   local NLI hallucination checker
│   └── pipeline.py       RAGService.ingest() / .ask()
├── chat_app.py           Flask routes for chat (+ /chat/stats for token/cost totals)
├── streamlit_app/        BART summarizer UI
├── ocr_processor.py      OCR for scanned pages
└── *_converter.py, txt.py  Office/TXT → PDF
eval/                     questions, rubric, ablation + generation scripts, results
docs/RAG_UPGRADE_JOURNAL.md   the step-by-step story of the upgrade
tests/                    unit + route tests
```

## 📸 Interface

| Home | Chat with PDF | Summarizer | Converter |
|---|---|---|---|
| ![Home](static/Images/Screenshot%20(31).png) | ![Chat](static/Images/Screenshot%20(29).png) | ![Summary](static/Images/Screenshot%20(38).png) | ![Converter](static/Images/Screenshot%20(33).png) |

## ⚠️ Known limitations

- The eval set is small (5 papers, 40 questions), so differences below about 6 points are within noise.
- Hallucination scores come from an automatic NLI proxy, not human judgement. It was checked on hand-made cases
  and spot-checked by hand, but it can miss claims that combine several excerpts.
- The Office converters need Windows with Microsoft Office installed. The chat and the summarizer are cross-platform.
- Scanned PDFs: the chat needs a text layer, while the summarizer has OCR (needs Poppler).

## 📝 License

MIT
