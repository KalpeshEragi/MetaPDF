# MetaPDF — Knowledge Base (durable facts for future sessions)

Read this first; go to the numbered docs for detail. Last updated 2026-10-04, `main` @ `6418b77`.
Tags: **[F]** source-verified · **[G]** Graphify · **[I]** inference · **[K]** upstream/background knowledge (unverified here) · **[?]** unverified/open.
Nothing has ever been **executed** in this audit series (no runtime verification).

## Document map (`dev_docs/metapdf_audit/`)
| File | Content |
|---|---|
| `01_architecture.md` | Structure, route table, workflow traces (chat RAG, summarizer, converters), config, state, errors, uncertainties U1–U9 |
| `02_technology_audit.md` | Dependency inventory vs real imports, overlaps, debt, security/maintenance risks, per-dependency verdicts |
| `03_llm_workflow_audit.md` | Token/latency/cost estimates per LLM workflow, waste found, 16 optimization options (O1–O16) |
| `04_modernization_plan.md` | Phased roadmap (P1.x cleanup → P2.x architecture → P3.x LLM tuning → P4.x quality → Phase 5 gates), sequencing, success metrics, open decisions D1–D6 |
| `KNOWLEDGE_BASE.md` | This file |

## What MetaPDF is [F]
Flask app (`app.py`) with three features reached from `/home`: (1) **chat with a PDF** (RAG, Gemini) at `/chat/`, (2) **PDF summarization** in a *separate Streamlit process* (`/streamlit` just redirects to `http://localhost:8501`), (3) **document→PDF converters** (`/docx /ppt /xl /txt`). No DB, no auth, no tests/CI/Docker/lockfile. Server-rendered Jinja + vanilla JS.

## Where things live (don't rescan) [F][G]
| Need | File / function |
|---|---|
| App wiring, secret key, CORS, blueprints | `app.py` (`debug=True`; `CORS(app)` all origins; registers home, chat, docx, ppt, xl, txt, streamlit) |
| Pages | `App/home.py` (`/`, `/home`, `/convertor`), `templates/` (ROOT), `static/` (ROOT) |
| Chat RAG | `App/chat_app.py`: `index()` L113 orchestrates `allowed_file` L33 → `get_pdf_text` L37 → `get_text_chunks` L48 → `get_vector_store` L57 / `load_vector_store` L73 → `get_conversational_chain` L83 |
| Chat UI logic | `templates/chat.html` inline JS (L96-220): `fetch('/chat/')` for upload (`pdf_files`) and question (`user_question`); `innerHTML` rendering; typewriter 30 ms/char |
| Summarizer | `App/streamlit_app/stream_app.py`: `extract_pages` L73 → `hybrid_extract_pages`; `preprocess_text` ~L132; `generate_smart_summary` ~L165; `load_model` L51 |
| OCR (added by commit `65420cc`) | `App/ocr_processor.py`: `hybrid_extract_pages` L239 (sparse page = ≤50 whitespace-collapsed chars → rasterize ALL pages at 200 dpi, EasyOCR `gpu=True` on sparse ones) |
| Converters | `App/docx_converter.py` (win32com Word), `ppt_converter.py` (comtypes PowerPoint), `xl_converter.py` (win32com Excel), `txt.py` (reportlab) |
| Streamlit redirect | `App/streamlit_embed.py` (hard-coded `localhost:8501`) |

## Models, services, parameters [F]
- Embeddings: Google `models/embedding-001`. Chat LLM: `models/gemini-1.5-flash-8b-001`, temperature 0.3, no max output tokens. Key `GOOGLE_API_KEY`. **Both IDs likely retired [K]** — chat may not work today **[?]**.
- Vector store: FAISS via `langchain_community`, pickle on disk at `<app.root_path>/data/faiss_index` (one global index, overwritten by every upload).
- Chunking (chat): `RecursiveCharacterTextSplitter` 10000/1000 chars. Retrieval: `similarity_search(q)` default k (**4 assumed [K]**), no score/filter/rerank. Chain: legacy `load_qa_chain(chain_type="stuff")`. Prompt: "maximum detail … leave no aspect unexplored", falls back to general knowledge when context lacks the answer; **no chat history is sent to the LLM**.
- Summarizer: local `facebook/bart-large-cnn` (transformers pipeline, fp16 on CUDA), beam 4; chunks <1000 chars; per-page; Fast/Balanced/High = 100/30, 150/50, 200/75 (max/min). Length policy bug: page word count sets per-chunk min length (≥120 for >500-word pages) and triggers a redundant second pass. "Complete summary" = concatenated page summaries (no reduce). Typewriter `sleep(0.01)` per char.
- PDF text: PyPDF2 (chat: concatenated, no pages, **no OCR**; summarizer: per page + OCR fallback). No other LLM providers anywhere (no Ollama/OpenAI/etc.).

## Config & environment [F]
- Required: `FLASK_SECRET_KEY` (`app.py`), `GOOGLE_API_KEY` (raises at import of `chat_app.py` → **whole app fails to start without it**). Two `.env` lookups: default `.env` (app.py) vs `<cwd>/env/.env` (chat_app). `env/` and `data/` are gitignored.
- No `MAX_CONTENT_LENGTH`; paths are cwd-relative (`static/uploads`, `static/pdfs`, `data/Uploads`) except FAISS (`app.root_path/data`).
- `app.py` imports COM converters unconditionally ⇒ app imports only where `pywin32`/`comtypes` exist (Windows) [I].
- `requirements.txt` (unpinned): missing `streamlit`, `torch`; dead `chromadb`, `requests`; near-dead `google-generativeai` (only `genai.configure`); OCR commit added `easyocr`, `pdf2image` (needs Poppler [K]), `Pillow`, `numpy`. `pywin32` and `comtypes` overlap.
- Local machine Python (3.13.7) is **not** the project env (Flask/LangChain/FAISS/PyPDF2/Streamlit absent) — resolved versions of the real stack are unknown.

## State [F]
Flask signed-cookie session: `chat_history` (display only) + `vector_store_created`. Cookie-size overflow after a few long answers is plausible **[I, untested]**. Streamlit: only `st.cache_resource` for the model; no `st.cache_data`/`session_state`.

## Endpoints [F]
`/`, `/home`, `/convertor`, `/streamlit` (302), `/chat/` GET/POST (`pdf_files` | `user_question`), `/chat/uploads/<f>` (dead), `/{docx,ppt,xl,txt}/` page, `/{…}/upload` POST (`file`) → JSON `{pdf_url}` or `{error}`, `/{…}/static/pdfs/<f>` download.

## Known issues index (details in docs 01–03)
- Security: `innerHTML` with user and model text (XSS); raw `file.filename` in docx/xl/txt (path traversal); `debug=True`; open CORS; no size limit; raw exception text returned with HTTP 200; `allow_dangerous_deserialization=True`; converters kill ALL Word/Excel/PowerPoint processes system-wide; no per-user isolation.
- Correctness: chat handles only first valid PDF per request; scanned PDFs in chat produce misleading "Invalid file format"; `images/` vs `Images/` case mismatch (git tracks `static/Images/`); `CoUninitialize` skipped on exceptions in COM converters; committed `instance/faiss_index/*` is stale (raw scan shows HTML-tutorial text; unreferenced by code).
- Efficiency (ESTIMATES, not measured): chat ≈10k input tokens/question for docs >12 pages and the whole doc for smaller ones; ≈600–1,200 output tokens/answer; summarizer ≈4–5 BART `generate()` calls/page with ≈60–75% of generated tokens discarded; Streamlit re-extracts (and re-OCRs all pages) on every rerun; results sit behind `st.button` so toggles/downloads may discard them **[I, untested]**; typewriter delays ≈12 min per 100-page run.
- Unused imports (AST-verified): `chat_app.py` (`secure_filename`, `url_for`, `uuid`), `home.py` (`os`, `send_from_directory`), `ppt_converter.py`/`txt.py`/`xl_converter.py` (`Flask`), `streamlit_embed.py` (`render_template`).

## Code-graph blast radius (Graphify `affected`) [G]
- Every chat helper has exactly one caller: `index()`. `chat_app.py` is imported only by `app.py`. ⇒ the RAG pipeline can be swapped behind an interface by touching `index()` and two `fetch` calls in `chat.html`.
- OCR is reachable only via `stream_app.extract_pages` (L93). Summarization logic is reachable only from the UI loop. `kill_*_processes` are local to each converter. Converters are imported only by `app.py`. **Chat and summarizer share no code.**

## Roadmap status (from `04_modernization_plan.md`) — nothing implemented
Order: P1.0 validation spikes → P1.1 reproducible env → P4.1/P4.2 logging + tests → P2.1/P2.2 shared extraction + RAG service → P4.3 eval set → P3.x tuning. Quick wins ahead of the safety net: dead-code/imports (P1.2), image paths (P1.3), security basics (P1.5), OCR sparse-only (P3.8), animation delays (P3.10). Do **not** rewrite frameworks or swap FAISS without measured limits. Open owner decisions D1–D6 (privacy, reduce-stage model, platform, scale, Flask vs Streamlit, eval documents) are listed in doc 04 §7.

## Open / unverified items [?]
Chat end-to-end with current model IDs; clean import on resolved LangChain; default `k`; Streamlit rerun/result-loss behavior; BART second-pass input truncation on `transformers 5.x`; cookie overflow; real `.env` layout; README vs code; `chat.html` client logic beyond fetch/typewriter; actual hardware (GPU/CPU). Validation plan: P1.0 in doc 04 (results to be logged in `05_validation_log.md`, not yet created).

## Graphify usage [G]
Graph in `graphify-out/` (uncommitted on `main` unless later added; ~182 nodes / 257 edges at last update; AST-only, all edges EXTRACTED). It also indexes `dev_docs` headings and README headings as noise nodes.
```
export PATH="$PATH:/c/Users/kalpesh/AppData/Roaming/Python/Python313/Scripts"   # graphify.exe is not on PATH by default
graphify query "<question>" --context call --budget 1500   # call edges only, less noise
graphify explain "<function()>"   graphify path "A" "B"   graphify affected "<node>" --depth 2   graphify god-nodes
graphify update .                 # after code changes; AST-only, no API cost
```
Graph is excellent for file/function/call discovery and blast radius; it cannot see config values, prompts, model names, numeric parameters, or runtime behavior — read the source for those. Workflow: Graphify → relevant files → targeted source read → record here.
