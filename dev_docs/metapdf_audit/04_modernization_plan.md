# MetaPDF — Modernization Roadmap (planning only)

Written 2026-10-04 against `main` @ `6418b77`. **Nothing here is implemented.** Inputs: `01_architecture.md`, `02_technology_audit.md`,
`03_llm_workflow_audit.md`, `KNOWLEDGE_BASE.md`. Tags: **FACT** (verified in source), **GRAPH** (Graphify), **ESTIMATE**/**INFERENCE**/**KNOWLEDGE**
as defined in the earlier docs. Items marked **[VALIDATE]** rest on an unverified claim and must be confirmed (cheaply) before work starts.

## 0. Principles
1. **Keep what works.** MetaPDF's product shape is sound: Flask pages, RAG chat, local summarizer, four converters. No rewrite to another web framework, SPA, or LLM framework without evidence that the current one blocks a goal.
2. **Measure before optimizing.** Every number in doc 03 is an estimate. Instrumentation and a small evaluation set (Phase 4a) come *before* retrieval/summarization tuning (Phase 3).
3. **Behavior-preserving first.** Cleanup and boundary work (Phases 1–2) must not change user-visible behavior except fixing defects; tune behavior only after tests exist.
4. **Small, reversible steps.** Each item below is intended to be one PR (or a few commits), with its own success metric.
5. **Decide explicitly** product-level questions (privacy, platform, multi-user) listed in §7; don't let them be decided by default.

## 1. Evidence summary (why this plan)
| Theme | Evidence (FACT unless tagged) |
|---|---|
| Install/deploy is not reproducible | `requirements.txt` unpinned; omits `streamlit`, `torch`; lists unused `chromadb`, `requests`; no lockfile/Python version/Docker/CI/tests (02 §2, §5) |
| Whole app only starts on Windows+Office with a Google key | `app.py` imports COM converters unconditionally; `chat_app.py` raises at import if `GOOGLE_API_KEY` unset (01 §7, 02 §5.11) |
| Chat can't be trusted to work today | Hard-coded Gemini 1.5 flash-8b and `embedding-001` IDs (likely retired — KNOWLEDGE), legacy LangChain chain APIs (KNOWLEDGE) |
| Chat cost/quality | ≈10k input tokens per question, no history, no thresholds, verbose open-ended prompt (03 §2) |
| Summarizer waste | Length policy bug, redundant 2nd pass, no caching, results behind `st.button` (03 §3) **[VALIDATE]** |
| Security basics | `innerHTML` on LLM/user text, raw filenames in 3 converters, `debug=True`, open CORS, no size limit, kills all Office processes (02 §6) |
| Shared mutable state | One global FAISS index; history in cookie (01 §8, 03 §2.3.6 **[VALIDATE]**) |

## 2. Blast radius from the code graph (GRAPH, `graphify affected`, depth 2)
The graph shows the code is loosely coupled, which makes incremental change cheap:
| Component | Callers / dependents | Implication |
|---|---|---|
| `get_pdf_text`, `get_text_chunks`, `get_vector_store`, `load_vector_store`, `get_conversational_chain` | each has exactly one caller: `index()` (`chat_app.py` L131/132/133/151/162) | The whole RAG pipeline can be re-implemented behind a service interface by touching only `index()` |
| `chat_app.py` | imported only by `app.py:6` | Blueprint can be refactored/replaced without side effects elsewhere |
| `index()` | god node (8 edges): routing + upload + chat + persistence in one function | Prime candidate for splitting (P2.2) |
| `extract_pages` → `hybrid_extract_pages` → `extract_text_from_image` → `_get_ocr_reader` | `ocr_processor.py` reachable only from `stream_app.extract_pages` (L93) | OCR can be moved into a shared module with a single call-site change |
| `preprocess_text`, `generate_smart_summary`, `load_model` | `generate_smart_summary` ← UI loop only | Summarization logic is extractable into a pure module (P2.3) |
| `kill_word_processes` / `kill_excel_processes` / `kill_ppt_processes` | called only by their own converter | Converter hardening is local to each file |
| Converters (docx/ppt/xl/txt) | each only imported by `app.py` | Shared-helper consolidation has no outside consumers |
| `templates/chat.html` fetch URLs | `fetch('/chat/')` ×2 (upload, question) | Splitting the route requires touching the template's JS (2 call sites) |
| Cross-pipeline links | **none** (chat and summarizer share no code) | Shared extraction (P2.1) is a new dependency, not a refactor of an existing one |

## 3. Roadmap overview and sequencing
```
Phase 1  Cleanup & reproducibility        (low risk, mostly S)       ── unblocks everything
Phase 4a Safety net: tests + token/latency logging + eval set        ── must precede Phase 3 tuning
Phase 2  Architecture (services, state, boundaries)                  ── enables clean Phase 3 changes
Phase 3  LLM workflow optimization (gated by 4a metrics)
Phase 4b Reliability: error handling, observability, CI hardening    ── ongoing, can overlap 2–3
Phase 5  Future architecture: decision gates, not commitments
```
Critical path: **1.0 validation spikes → 1.1 reproducible env → 4.1/4.2 logging+tests → 2.1/2.2 services → 4.3 eval set → 3.x tuning.**
Quick wins that can ship before the safety net (no behavior tuning, low risk): 1.2, 1.3, 1.5, 3.10 (animation delays), 3.8 (OCR only sparse pages — correctness-equivalent).

Effort key: **S** ≈ <½ day, **M** ≈ 1–3 days, **L** ≈ >3 days (rough, one developer). Risk: L/M/H.

---
## Phase 1 — Cleanup

### P1.0 Validation spikes (before any change) — S
- **Problem:** several high-impact claims are unverified (INFERENCE/KNOWLEDGE).
- **Evidence:** 02 §10 and 03 §7 list them.
- **Proposed:** in a throwaway venv, run (a) chat upload+question end-to-end with the configured Gemini/embedding IDs; (b) `python -c "import App.chat_app"` against the resolved LangChain version; (c) Streamlit manual test: generate summaries then toggle "Show combined summary" / click a download button — do results persist?; (d) measure cookie size of `session` after N chat turns; (e) record installed versions (`pip freeze`); (f) default `k` of `similarity_search`.
- **Files:** none changed (record results in `dev_docs/metapdf_audit/05_validation_log.md`, new).
- **Dependencies affected:** none. **Benefit:** converts INFERENCE into FACT; may reveal chat is already broken (making 2.2/3.x urgent). **Risk:** L. **Complexity:** S. **Depends on:** a Google API key and a Windows box. **Success:** each [VALIDATE] item has a recorded yes/no with evidence.

### P1.1 Reproducible environment — S/M
- **Problem:** installs are non-deterministic and incomplete.
- **Evidence:** 02 §2 table: 2 dead (`chromadb`, `requests`), 2 undeclared (`streamlit`, `torch`), 1 near-dead (`google-generativeai`); new OCR deps (`easyocr`, `pdf2image`, `Pillow`, `numpy`) also unpinned; `pdf2image` needs Poppler (KNOWLEDGE).
- **Proposed:** split into `requirements/base.txt` (Flask, flask-cors, python-dotenv, PyPDF2→pypdf later, reportlab), `requirements/chat.txt` (LangChain pieces, faiss-cpu, langchain-google-genai), `requirements/summarizer.txt` (streamlit, torch, transformers, easyocr, pdf2image, Pillow, numpy), `requirements/windows-converters.txt` (pywin32, comtypes, psutil); pin versions from the working venv (P1.0e) with a lock/constraints file; document Python version and system deps (Poppler, Office) in README; remove `chromadb`/`requests` after confirming no transitive need (`pip check`, import test).
- **Affected:** `requirements.txt`, README. **Dependencies affected:** all. **Benefit:** repeatable setup; smaller install for chat-only/dev; removes heavy unused wheel. **Risk:** M (version pins that don't resolve together on other machines). **Depends on:** P1.0. **Success:** fresh venv install + smoke test passes on a clean machine; `pip check` clean; install size reduced (record MB before/after).

### P1.2 Remove dead code and unused imports — S
- **Problem/evidence:** AST-verified unused imports in 8 files (02 §5.1); dead `uploaded_file()` route + `UPLOAD_FOLDER`/`data/Uploads` (chat never saves files); commented-out blocks in `home.py`, `stream_app.py`; stale committed `instance/faiss_index/*` (raw scan shows HTML-tutorial text, no code reference).
- **Proposed:** delete unused imports; remove `uploaded_file` route and unused `UPLOAD_FOLDER` config (confirm no template uses `chat_app.uploaded_file`); `git rm instance/faiss_index/` after confirming nothing loads it; remove commented-out code.
- **Affected:** `chat_app.py`, `home.py`, `ppt_converter.py`, `txt.py`, `xl_converter.py`, `streamlit_embed.py`, `app.py`, `instance/`. **Benefit:** less noise, no pickle in repo. **Risk:** L. **Complexity:** S. **Depends on:** nothing (best after P1.0 so removal is verified against a running app). **Success:** `pyflakes`/`ruff` unused-import count = 0; app routes unchanged (route list diff empty except removed route).

### P1.3 Fix static asset path case — S
- **Evidence:** git tracks `static/Images/…`; `home.html`, `ppt.html`, `txt.html`, `xl.html` reference `images/…` (02 §5.7). Breaks on case-sensitive filesystems.
- **Proposed:** pick one casing (rename dir to lowercase `images/` via `git mv`, update the two templates using `Images/`) — or normalize all references. **Affected:** templates, `static/`. **Risk:** L (Windows case-insensitive rename needs a two-step `git mv`). **Success:** link checker over all templates returns 0 missing assets when run on Linux/CI.

### P1.4 Centralize configuration — M
- **Problem/evidence:** two `.env` locations (`app.py` default vs `<cwd>/env/.env`), import-time `raise` for `GOOGLE_API_KEY` (kills converters too), hard-coded model IDs (`chat_app.py:61,77,102`), chunk sizes, Streamlit URL (`streamlit_embed.py`), cwd-relative paths.
- **Proposed:** `config.py` (dataclass or `os.environ` with defaults) with: `FLASK_SECRET_KEY`, `GOOGLE_API_KEY` (required only when chat enabled), model IDs, chunk size/overlap, `k`, `SUMMARIZER_URL`, `DATA_DIR`, `UPLOAD_DIR`, `MAX_CONTENT_LENGTH`, `DEBUG`, feature flags (`ENABLE_CHAT`, `ENABLE_OFFICE_CONVERTERS`). Single `.env` load. Absolute paths from a base dir. Provide `.env.example`.
- **Affected:** `app.py`, `chat_app.py`, `streamlit_embed.py`, converters (paths), `.gitignore`. **Benefit:** app boots without a key (converters/home still work); configurable models (needed for model-ID migration and P3.x). **Risk:** M (path changes alter where files land). **Complexity:** M. **Depends on:** P1.0. **Success:** app starts with no `GOOGLE_API_KEY` (chat returns a clear "not configured" response); all paths absolute and independent of cwd (test by launching from another directory).

### P1.5 Security quick wins (behavior-preserving) — M
- **Evidence (02 §6):** `innerHTML` with user text (`chat.html:178-181`) and model text (`:108`, `:204-208`); raw `file.filename` in docx/xl/txt; `debug=True`; `CORS(app)`; no `MAX_CONTENT_LENGTH`; exception text returned (`chat_app.py:184`); `allow_dangerous_deserialization=True`.
- **Proposed:** `textContent`/escaped rendering in chat.html; `secure_filename` + uuid prefix in docx/xl/txt (mirroring ppt); delete inputs after conversion (as ppt does); set `MAX_CONTENT_LENGTH` (value from config); `debug` from config default False; CORS restricted to configured origins (or removed if same-origin only); generic error messages + server-side logging; keep deserialization flag but only for indices created by the app under `DATA_DIR`.
- **Affected:** `templates/chat.html`, `docx_converter.py`, `xl_converter.py`, `txt.py`, `app.py`, `chat_app.py`. **Benefit:** closes XSS/path-traversal/debugger exposure. **Risk:** L–M (413 handling must work — see P4.4). **Complexity:** M. **Depends on:** P1.4 for config values (can ship minimal hard-coded first). **Success:** targeted tests (P4.2): `<script>` in question and in a mocked answer renders inert; `../../x.docx` filename saved under upload dir only; oversize upload → 413 JSON.

### P1.6 Consolidate converter boilerplate — M
- **Problem/evidence:** four near-identical `upload_file()`/`download_pdf()` implementations with divergent validation (case-sensitive `endswith` vs `splitext().lower()`), status codes (ppt returns 200 on missing file), and cleanup (only ppt).
- **Proposed:** shared helper module (`App/converters/common.py`): `validate_and_save(file, allowed_ext)`, `unique_names()`, `respond_ok/err`, `cleanup()`; per-format modules keep only `convert(src, dst)`. Decide COM library: consolidate on one of `pywin32`/`comtypes` (`pythoncom` is needed by all three anyway — INFERENCE) after a spike that ppt works via `win32com`.
- **Affected:** `docx_converter.py`, `ppt_converter.py`, `xl_converter.py`, `txt.py`, templates' fetch URLs unchanged. **Dependencies affected:** `comtypes` (removable). **Benefit:** one place to fix bugs; consistent behavior; one fewer dependency. **Risk:** M (cannot test COM without Office; mock + manual check). **Complexity:** M. **Depends on:** P1.5 (filename handling). **Success:** LOC reduction in the four modules (record), identical JSON contract verified by tests, manual conversion of one file per format passes.

### P1.7 Replace PyPDF2 with pypdf — S
- **Evidence:** PyPDF2 deprecated (KNOWLEDGE); only 3 call sites: `chat_app.get_pdf_text`, `stream_app.extract_pages` (+ `ocr_processor`).
- **Proposed:** switch imports to `pypdf` (largely API-compatible); regression-compare extracted text on the sample PDFs. **Affected:** `chat_app.py`, `stream_app.py`, `ocr_processor.py`, requirements. **Risk:** L–M (extraction output differences). **Depends on:** P4.2 baseline text fixtures ideally. **Success:** extracted text equal or better on fixture set (diff report), no regressions in tests.

---
## Phase 4a — Safety net (do right after P1.1; placed here because Phase 3 depends on it)

### P4.1 Token / latency / cost tracking — M
- **Problem/evidence:** no token or latency logging anywhere (03 §0). All of doc 03 is estimated.
- **Proposed:** a small `metrics` helper: per request log `{request_id, route, doc_chars, n_chunks, k, retrieved_chars, prompt_tokens, output_tokens (Gemini usage metadata if exposed by the wrapper), embedding_calls, ms_extract, ms_embed, ms_retrieve, ms_llm, ms_total}`; summarizer: per page `{chunks, generate_calls, encoder_tokens, decoder_tokens, ms}`, OCR pages and ms. Write JSON lines to `DATA_DIR/metrics.jsonl`; token counts via model-reported usage where available, else a tokenizer estimate flagged as estimated.
- **Affected:** `chat_app.py` (around calls), `stream_app.py`, new `metrics.py`. **Benefit:** replaces estimates with data; prerequisite for every Phase 3 decision. **Risk:** L. **Complexity:** M. **Depends on:** P1.4. **Success:** after a scripted session, a report script prints p50/p95 input/output tokens and latency per stage; estimates in doc 03 §2.2/§3.3 are reconciled with measured values.

### P4.2 Test suite foundation — M/L
- **Problem/evidence:** zero tests (02 §1).
- **Proposed:** `pytest` with: unit tests (chunker params, `preprocess_text`, length policy, `allowed_file`, filename sanitization); Flask test-client route tests with fakes for Gemini/embeddings (inject via the service interface from P2.2, or monkeypatch before then); converter tests with COM mocked (txt tested for real); golden-text fixtures for extraction on 3–4 small PDFs (text, scanned, mixed); a smoke test that boots the app with converters disabled (P2.5).
- **Affected:** new `tests/`; minimal code changes (injection points). **Risk:** L. **Depends on:** P1.1, P1.4. **Success:** CI-runnable suite (<1 min, no network, no Office) with coverage report; ≥1 test per route; every behavior-changing item below must add/adjust a test.

### P4.3 Evaluation datasets — M
- **Problem:** no way to judge whether smaller chunks/k/threshold/prompt changes preserve quality.
- **Proposed:** `eval/` with 4–6 representative PDFs (short text, long text, table-heavy, scanned, multi-section report) — only documents the owner may keep in the repo or stored outside git with a manifest + hashes; 30–60 questions with gold answers and gold page/chunk locations (lookup, multi-paragraph, cross-section, unanswerable, follow-up pairs); summary rubric (key-point checklist per doc). Scripts: retrieval metrics (recall@k, MRR, tokens-of-context), answer metrics (manual rubric or LLM-judge with a *different* model to avoid self-grading, plus a faithfulness check against retrieved text), summary metrics (key-point coverage, compression ratio, runtime).
- **Affected:** new `eval/`. **Risk:** L (effort, not code). **Complexity:** M. **Depends on:** P4.1 (token logging), service interfaces (P2.2) for scripted runs. **Success:** `python -m eval.run` produces a baseline report committed to `dev_docs/` for the *current* behavior; every Phase 3 item compares against it (no regression in recall@k / answer score beyond an agreed tolerance, e.g. ≤2 points absolute).

---
## Phase 2 — Architecture

### P2.1 Shared document-processing module — M
- **Problem/evidence:** two PDF extraction paths (chat: PyPDF2 concatenation, no OCR, no pages; summarizer: per page + OCR) (01 W1/W2); chat returns misleading "Invalid file format" for scanned PDFs (03 §2.3.9). Graph: `get_pdf_text` has one caller; `ocr_processor` has one entry (`extract_pages`).
- **Proposed:** package `App/docproc/` exposing `extract_pages(file_or_bytes) -> list[Page(num, text, source: "text"|"ocr")]`, header/footer stripping (opt), `clean_text`. Chat and summarizer both call it. OCR stays optional (lazy import of easyocr/pdf2image; `OCR_ENABLED` flag; clear message if Poppler missing). Cache results by file hash (see P2.4).
- **Affected:** `chat_app.get_pdf_text`, `stream_app.extract_pages`, `ocr_processor.py` (moved), requirements split. **Dependencies affected:** pypdf, easyocr, pdf2image. **Benefit:** one extraction implementation; chat gains OCR and page numbers (enabling P3.4); dedup. **Risk:** M (chat behavior changes for scanned PDFs: heavier compute). **Depends on:** P1.7, P4.2. **Success:** both apps use the same function (grep/graph shows one definition); golden fixtures pass; scanned PDF in chat yields answers instead of an error.

### P2.2 Extract a RAG service from the route — M/L
- **Problem/evidence:** `index()` (God node, 8 edges, L113–L187) handles routing, validation, ingestion, retrieval, generation, history, and error mapping in one function; one caller per helper (GRAPH). Legacy LangChain APIs are imported at module top-level.
- **Proposed:** `App/rag/` with narrow interfaces:
  - `Ingestor.ingest(doc_id, pages) -> IndexInfo`
  - `Retriever.retrieve(doc_id, query, budget) -> list[Chunk]`
  - `Answerer.answer(question, chunks, history) -> Answer(text, usage)`
  and thin Flask routes `POST /chat/upload`, `POST /chat/ask`, `GET /chat/` (update the two `fetch` calls in `chat.html`). Implementation initially wraps the *existing* behavior (same chunking/prompt) so behavior is preserved; replace `load_qa_chain` with an explicit prompt + direct model call behind the `Answerer` interface (removes the deprecated chain API); LangChain remains only for splitter/FAISS/Google wrappers, or is dropped later if desired.
- **Affected:** `chat_app.py`, `templates/chat.html` (2 fetch URLs), new `App/rag/`. **Dependencies affected:** `langchain` (legacy chain API removed), possibly `google-generativeai`. **Benefit:** testable seams (fake Answerer/Retriever), enables caching/routing/eval hooks; limits future change to one module. **Risk:** M (behavior drift — mitigate with characterization test on fixtures before/after). **Depends on:** P1.4, P4.2; **P1.0 result** (if chat already broken, this becomes the fix). **Success:** route functions < ~30 lines each; unit tests run the full flow with fakes; on the eval set the answers' recall@k and token counts match the baseline (behavior-preserving).

### P2.3 Extract summarization logic from the Streamlit script — M
- **Problem/evidence:** `stream_app.py` mixes UI (`st.*`) with logic (`preprocess_text`, `generate_smart_summary`, length policy); module-level script is untestable. Graph: logic functions are only reached from the UI loop.
- **Proposed:** `App/summarization/` with pure functions: `plan_chunks(text)`, `length_targets(chunk, mode)`, `summarize_pages(pages, settings, summarizer)`, `reduce_summaries(...)`; `load_model()` stays a cached resource in the UI layer. `stream_app.py` becomes a thin UI over the service. This also lets Flask expose the same service later (P5.x) without Streamlit.
- **Affected:** `stream_app.py`, new module, tests. **Risk:** M (Streamlit semantics around reruns). **Depends on:** P2.1, P4.2. **Success:** summarization functions importable and tested without Streamlit/torch (model injected); UI file shrinks (record LOC); same outputs for fixture inputs.

### P2.4 State management: per-document/per-session stores — M/L
- **Problem/evidence:** one global FAISS dir overwritten by any upload; `session['vector_store_created']` is a global flag; `chat_history` in a signed cookie (4 KB limit — **[VALIDATE]** P1.0d); no content hashing (03 §2.3.5, §2.3.8).
- **Proposed:** `DocumentStore` keyed by SHA-256 of PDF bytes under `DATA_DIR/docs/<hash>/{pages.json, index/, meta.json}`; session holds only `doc_id`; chat history stored server-side (file/SQLite keyed by session id) with a bounded window; garbage collection by age. Re-upload of the same file reuses stored pages/index (no re-extract, no re-embed). Replace pickle-based FAISS persistence only if a safer format is adopted later.
- **Affected:** `chat_app.py`/`App/rag`, `docproc` cache, `chat.html` (reads history from API instead of session render, optional), `.gitignore`. **Benefit:** multi-user isolation, fixes overwrite bug, eliminates re-embedding on repeats, removes cookie-size failure mode. **Risk:** M (migration; storage growth; cleanup policy). **Complexity:** M/L. **Depends on:** P2.1, P2.2. **Success:** two sessions upload different PDFs and each queries its own doc (test); re-upload of identical bytes → 0 embedding calls (metric from P4.1); history survives >20 turns without cookie growth.

### P2.5 Make heavy/optional features optional (lazy registration) — S/M
- **Problem/evidence:** unconditional imports of COM modules and eager `GOOGLE_API_KEY` check make the whole app Windows+Office+key dependent (02 §5.11).
- **Proposed:** blueprints registered conditionally by config/platform (`ENABLE_OFFICE_CONVERTERS` auto-false off Windows; TXT converter always on); lazy imports inside converter modules; the home page hides/disables unavailable tools with a message. `create_app()` factory in `app.py` (no import-time side effects: `makedirs`, `load_dotenv`, `raise`).
- **Affected:** `app.py`, converter modules, `home.html`/`convertor.html` (conditional links). **Benefit:** app runs and is testable on Linux/CI/containers; failures isolated per feature. **Risk:** L–M. **Depends on:** P1.4. **Success:** `pytest` smoke test boots the app on Linux with converters disabled; `/home`, `/txt/`, `/chat/` respond.

### P2.6 Decide the Flask/Streamlit boundary — S (decision) → M/L (if changed)
- **Problem/evidence:** two servers, hard-coded `localhost:8501` redirect, no shared sessions/styling; Streamlit rerun model drives several defects (03 §3.4).
- **Options:** (A) keep Streamlit; make URL configurable; add health check + launch script (cheapest). (B) Move summarization to a Flask endpoint + background job (polling) using the P2.3 service; drop Streamlit and `st.cache_resource` reliance; unify look/feel. (C) Embed Streamlit via iframe (not recommended; cookie/CSP complexity).
- **Recommendation:** do (A) now; revisit (B) after P2.3 and P3.6–3.8 *if* the Streamlit rerun issues persist or a single deployable is wanted. **Evidence required to choose B:** Streamlit defects remain after caching fixes, or deployment needs a single process. **Risk:** (A) L; (B) M–H. **Success (A):** `SUMMARIZER_URL` configurable; one command starts both; link works in a different host/port.

---
## Phase 3 — LLM workflow optimization (each item gated by P4.3 eval and P4.1 metrics)

### P3.1 Retrieval retune: chunk size, k, score threshold, token budget, small-doc full context — M
- **Problem/evidence:** 10,000/1,000-char chunks, default k (≈4), ≈10k input tokens/question; small docs fully sent; no threshold/early exit (03 §2.2–2.3, O1/O2).
- **Proposed:** make chunk size/overlap/k configurable (P1.4); sweep on the eval set (e.g., chunk 800/1200/1600/2400 chars × k 3/4/6/8 × overlap 10–15%); adopt a **token-budgeted** context (cap by tokens, not chunk count); use `similarity_search_with_score` with a calibrated cutoff; if best score below cutoff → return "not found" without an LLM call; if total document tokens ≤ budget → send whole document; optional neighbour expansion for the top chunk.
- **Affected:** `App/rag` (Retriever), config, eval scripts, re-index (stored indices become invalid — include `index_version` in meta). **Dependencies affected:** none new. **Benefit (ESTIMATE, to be measured):** input tokens/question 10k → ≈1–2.5k if answers are localized (03 O1); off-topic questions cost 0 LLM tokens. **Risk:** M (quality regressions on multi-section questions → mitigated by eval + neighbour expansion). **Complexity:** M. **Depends on:** P2.2, P2.4 (index versioning), P4.1, P4.3. **Success:** on eval set, p50 context tokens ↓ ≥60% **and** recall@k and answer score within tolerance of baseline; unanswerable-question handling precision ↑.

### P3.2 Prompt and output control — S
- **Problem/evidence:** "maximum detail … leave no aspect unexplored" + fallback to general knowledge; no `max_output_tokens` (`chat_app.py:84-109`); output ≈ 600–1,200 tokens (ESTIMATE); 30 ms/char reveal.
- **Proposed:** concise-by-default grounded prompt; explicit rule for missing info (state absence; optionally a flagged "outside the document" note controlled by a setting); cite page numbers (needs P3.4); `max_output_tokens` configured; "Detailed answer" toggle in UI (sends a flag) for long form.
- **Affected:** `App/rag` Answerer prompt, `chat.html` (toggle), config. **Benefit (ESTIMATE):** output tokens −50–70%; ≈12–20% total per-question spend; fewer ungrounded answers; shorter wait. **Risk:** L–M (users who liked long answers → toggle). **Depends on:** P2.2, P4.3 (faithfulness metric). **Success:** mean output tokens ↓ ≥40%; faithfulness score ≥ baseline; no increase in "unhelpful" ratings on the eval rubric.

### P3.3 Conversation handling: bounded history + standalone-question rewrite — M
- **Problem/evidence:** history not sent to the model; follow-ups retrieve poorly (03 §2.3.5).
- **Proposed:** server-side history (P2.4) → last N turns (N≈2–3) compacted; **rewrite step only when needed** (heuristic: pronouns/ellipsis, or short question with history) via the cheapest model/local small model, used for *retrieval query*; pass compact recent turns to the Answerer. Add per-turn metrics.
- **Affected:** `App/rag`, history store, `chat.html`. **Benefit:** better follow-up quality; fewer re-asks (each re-ask ≈ a full call). Token cost: +≈300 in/+30 out on rewritten turns only. **Risk:** M (rewriter drift/hallucinated constraints → eval on follow-up pairs). **Depends on:** P2.4, P3.1, P4.3. **Success:** follow-up pair accuracy ↑ vs baseline by an agreed margin; added tokens/turn within budget; rewrite rate logged.

### P3.4 Page-aware chunks, metadata, citations, boilerplate stripping — M
- **Problem/evidence:** pages concatenated; no metadata; repeated headers/footers feed both pipelines (03 §2.3.10, §3.4.7).
- **Proposed:** chunk per page-aware splitter retaining `{doc_id, page_start, page_end}`; strip lines repeated on >~50% of pages (configurable); return page citations in answers; allow explicit scoping ("on page 5").
- **Affected:** `docproc`, `App/rag`, `chat.html` (render citations). **Benefit:** verifiability, scoped retrieval, small token savings (assumption: 1–5% boilerplate). **Risk:** M (splitter behavior change; must re-index). **Depends on:** P2.1, P2.2, P3.1. **Success:** ≥X% of answers carry correct page citations on the eval set; boilerplate removal reduces chunk tokens with no recall loss.

### P3.5 MMR / reranking (conditional) — M
- Do only if eval shows recall misses at small k. Over-fetch (15–20), MMR or small local cross-encoder to keep 3–5; dedupe overlapping chunks. **Risk:** M (new dependency, latency ≈ tens–hundreds ms — ESTIMATE). **Success:** recall@k_context ↑ without raising context tokens. **Depends on:** P3.1, P4.3.

### P3.6 Summarizer length policy and second pass — S/M
- **Problem/evidence:** page `word_count` drives per-chunk `min_length` (up to 120 for ~250-token chunks), forcing ≥~50% retention, then a redundant second pass (03 §3.2); second pass lacks `num_beams`/penalty settings and may exceed BART's input limit (**[VALIDATE]**).
- **Proposed:** per-chunk length targets from compression ratios mapped to the Fast/Balanced/High slider; remove automatic page-level re-summarization (or make it an explicit reduce step with budget); consistent generation params; guard input length.
- **Affected:** `App/summarization` (or `stream_app.py` if P2.3 not yet done). **Benefit (ESTIMATE):** −50–65% decoder tokens, ≈1 fewer `generate()` per page, ≈30–50% faster. **Risk:** M (summary style changes). **Depends on:** P4.1 (baseline), P4.3 (key-point rubric). **Success:** per-page generated tokens and runtime ↓ vs baseline; key-point coverage ≥ baseline (tolerance); no truncation warnings.

### P3.7 Summarizer caching and session state — S/M
- **Problem/evidence:** `extract_pages` uncached (L251), results only inside `if st.button` (L290) (**[VALIDATE]**).
- **Proposed:** `st.cache_data` for extraction keyed by file hash; summaries cached per `(file hash, page, settings hash)`; display from `st.session_state` so toggles/downloads don't discard results; unblock combined-summary checkbox.
- **Affected:** `stream_app.py` (or UI layer after P2.3). **Benefit:** up to 100% of repeat extraction/OCR/BART work; fixes functional bug if confirmed. **Risk:** L–M (cache invalidation on settings change). **Depends on:** P1.0c, ideally P2.1. **Success:** second interaction after generation triggers 0 extraction/BART calls (metric); manual test passes.

### P3.8 OCR only for sparse pages — S
- **Problem/evidence:** `convert_from_bytes(content, dpi=200)` rasterizes every page when any page is sparse (`ocr_processor.py` L282-288).
- **Proposed:** rasterize only sparse indices (page-range arguments), cache OCR text by `(file hash, page)`, make GPU use configurable (`gpu=True` is hard-coded), optional lower dpi.
- **Affected:** `ocr_processor.py` / `docproc`. **Benefit:** render work ∝ sparse/total pages (e.g., 2/100 ⇒ ≈98% fewer renders), lower memory spike. **Risk:** L. **Depends on:** none (can precede P2.1). **Success:** same OCR text on fixtures; render count and peak memory reduced (measured).

### P3.9 Hierarchical (map-reduce) document summary — M
- **Problem/evidence:** "complete summary" is concatenation (≈15–20k tokens for 100 pages — ESTIMATE).
- **Proposed:** map = page/section summaries (P3.6); reduce = group ~8–10 summaries → section summary → final 300–600 token overview. Reduce stage model is a **decision**: local BART (private, input-limited, grouped) vs one API call over ≈15–20k tokens (better quality, sends summaries — not raw text — to the provider). Make it a setting.
- **Affected:** `App/summarization`, UI. **Benefit:** a real overview instead of a pile; deliverable ↓ ≈95%+. **Risk:** M (quality/privacy trade-off). **Depends on:** P3.6, P3.7, P4.3, decision D2 (§7). **Success:** overview rated ≥ baseline on key-point coverage with ≤ target length; runtime added ≤ agreed bound.

### P3.10 Remove per-character animation delays — S
- **Evidence:** Streamlit `time.sleep(0.01)` + one render per char; chat 30 ms/char (03 §3.4.8, §2.3.11).
- **Proposed:** render once or in coarse steps; keep animation as a short capped effect or CSS-only. **Affected:** `stream_app.py`, `chat.html`. **Benefit:** minutes saved per long run (ESTIMATE: ≈12 min per 100 pages + combined). **Risk:** L (UX taste). **Depends on:** none. **Success:** time-to-visible-result per page ≈ model time only.

### P3.11 Embedding/index caching and local-embedding spike — M (spike S)
- **Proposed:** content-hash cache comes from P2.4. Separately, a **spike** comparing a local sentence-embedding model vs Google `embedding-001` on the eval set (recall@k, index time, memory) — adopt only if quality within tolerance. **Risk:** M (full re-index; model download; GPU/CPU load). **Benefit:** removes embedding API tokens/egress (≈8k–166k tokens/upload per 03 §2.2). **Depends on:** P2.2, P4.3. **Success:** documented spike result; decision recorded.

### P3.12 Model routing — deferred (conditional)
- **Evidence:** configured model is already the cheapest tier (KNOWLEDGE); volumes unknown. **Proposal:** do not build a router now. Revisit if P4.1 data shows (a) a mix of trivial lookups and hard synthesis questions with meaningful spend, or (b) a cheap local model reliably handles rewrite/classification. **Immediate action instead:** make model IDs configurable (P1.4) and migrate off retired IDs (P1.0/P2.2).

---
## Phase 4b — Reliability & observability (parallel to Phases 2–3)

### P4.4 Error handling — M
- **Evidence:** blanket `except Exception` returning HTTP 200 with raw message (`chat_app.py:181-185`); helpers `print()` and swallow errors; blueprint-level 413/500 handlers (413 never produced: no size config; blueprint-level handler may not fire for request-size errors — INFERENCE); `CoUninitialize` skipped on exceptions in COM converters; summarizer silent `continue`/`pass`.
- **Proposed:** typed domain errors (`NotConfigured`, `UnsupportedFile`, `ExtractionFailed`, `ProviderError`, `Timeout`); consistent JSON error schema with correct HTTP status; app-level 413/404/500 handlers; `try/finally` for COM init/quit; retries with backoff + timeouts for Google calls; user-safe messages; log details server-side.
- **Affected:** `chat_app.py`/`App/rag`, converters, `stream_app.py`, `chat.html` error display. **Risk:** L–M. **Depends on:** P1.4, P2.2 (cleanest after). **Success:** tests assert status codes and schema; no raw exception text in responses; Office processes released after failures (manual check).

### P4.5 Observability — S/M
- **Proposed:** `logging` configuration (JSON or key=value, request IDs), replace `print`; health endpoint (`/healthz`: app up, chat configured, summarizer reachable); metrics from P4.1 summarized in a small report script/dashboard; log levels via config.
- **Affected:** all modules (replace prints), `app.py`. **Risk:** L. **Depends on:** P4.1. **Success:** every request produces one structured log line with request ID; health endpoint reflects real dependency state.

### P4.6 CI and quality gates — S
- **Proposed:** GitHub Actions: install (Linux) → `ruff`/`pyflakes` → `pytest` (converters disabled) → optional Windows job for converter mocks; fail on unused imports, new `print`, failing eval-smoke (tiny, offline). **Depends on:** P1.1, P2.5, P4.2. **Success:** green CI on every PR; badge optional.

---
## Phase 5 — Future architecture (decision gates, not commitments)
Evaluate after Phases 1–4 deliver data. For each: **go/no-go criterion** and a minimal first step.

| Direction | Assessment from current evidence | Go criterion | First step |
|---|---|---|---|
| **Modular AI pipelines** | Natural outcome of P2.1–2.3 (extract → chunk → index → retrieve → answer; extract → plan → summarize → reduce) with swappable stages and shared metrics | Already justified by Phase 2; do it | Stage interfaces + stage-level metrics |
| **Adaptive retrieval** | Likely worthwhile: route by document size (full-context vs retrieve), query type (lookup vs overview), and score confidence | P4.1 shows large variance in doc sizes/question types; eval shows full-context beats RAG for small docs | Implement the P3.1 routing rules as an explicit strategy object |
| **Persistent document intelligence** | Strong fit: store pages, OCR text, embeddings, summaries per content hash (P2.4) so every feature reuses them; enables multi-document chat later | Repeated uploads/multi-doc demand; storage budget agreed | Add a small SQLite/JSON metadata index over `DocumentStore` |
| **Local/cloud hybrid inference** | Already hybrid (local BART, cloud Gemini). Candidates: local embeddings (P3.11), local rewrite/classification, optional local generator via Ollama for privacy mode | Privacy decision D1 (§7); eval shows acceptable quality/latency locally | Provider interface with `local`/`cloud` implementations behind config |
| **Model routing** | Weak case today (already cheapest tier; low volume) | P4.1 spend concentrated in hard-vs-easy mix with measurable savings ≥ some threshold | Only after provider interface exists |
| **Agentic workflows** | No current need: tasks are fixed pipelines. Possible later for multi-document comparison or "choose summary vs retrieval vs OCR" | A concrete user feature that needs tool selection and iteration; eval shows fixed pipelines fail it | Prototype outside main app with a small tool set (retrieve, summarize, extract page) |
| **Workflow-level optimization** | Per-request token/latency budgets; cache-aware planning; cost dashboard | P4.1 data in place | Per-request budget object passed through stages |

Do **not** pursue: framework rewrite (FastAPI/React) or vector-DB swap (Chroma/pgvector) without a measured limit of the current Flask+FAISS (single-node, small corpora); revisit only if multi-user scale or concurrent indexing requires it.

---
## 6. Prioritized backlog (impact ÷ effort, respecting dependencies)
| Rank | Item | Why now | Effort | Risk |
|---|---|---|---|---|
| 1 | P1.0 validation spikes | Turns guesses into facts; may reveal chat is broken | S | L |
| 2 | P1.1 reproducible env | Unblocks everything | S/M | M |
| 3 | P1.2, P1.3 dead code / image paths | Trivial, immediate | S | L |
| 4 | P1.5 security quick wins | Real exposure; small diffs | M | L–M |
| 5 | P4.1 + P4.2 instrumentation + tests | Gate for Phase 3 | M+M | L |
| 6 | P3.8, P3.10 OCR sparse-only, remove typewriter delays | Safe wins in compute/latency | S+S | L |
| 7 | P3.7 summarizer caching/state | Highest-confidence compute saver; likely bug fix | S/M | L–M |
| 8 | P1.4 config + P2.5 optional features | Boots without key/Office; configurable models | M+S | M |
| 9 | P2.1, P2.2 shared extraction + RAG service | Seams for all LLM work; replaces legacy chain API | M+M/L | M |
| 10 | P4.3 eval set | Required to tune retrieval/prompt safely | M | L |
| 11 | P3.1 + P3.2 retrieval retune + prompt/output control | Largest API-cost lever | M+S | M |
| 12 | P3.6 summarizer length policy | ≈50–65% fewer decoder tokens (ESTIMATE) | S/M | M |
| 13 | P2.4 state stores | Multi-user correctness, caching | M/L | M |
| 14 | P3.3, P3.4 history/rewrite, citations | Quality improvements | M+M | M |
| 15 | P1.6, P1.7 converter consolidation, pypdf | Maintainability | M+S | M |
| 16 | P3.9 hierarchical summary | Quality for long docs | M | M |
| 17 | P4.4–P4.6 errors, observability, CI | Reliability | M+S/M+S | L |
| 18 | P3.5, P3.11, P3.12, Phase 5 | Conditional on data | — | — |

## 7. Open decisions for the owner
- **D1 Privacy:** is sending document text to Google acceptable by default? Offer a local-only mode (local embeddings + local generator) or keep chat cloud-only?
- **D2 Reduce-stage model for document summaries:** local BART (private) vs one API call over page summaries.
- **D3 Platform:** is Windows+Office a hard requirement for converters, or should a portable path (e.g., LibreOffice headless) be evaluated? (Not planned here; needs a spike.)
- **D4 Users/scale:** single-user local tool vs multi-user service (drives P2.4 depth, auth, rate limits, storage GC).
- **D5 Streamlit vs Flask** for the summarizer (P2.6), after P3.7 shows what remains broken.
- **D6 Eval documents:** which PDFs may be committed or stored for evaluation.

## 8. Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Chat already failing on retired model IDs / new LangChain | Medium (KNOWLEDGE) | High | P1.0 first; config-driven IDs; `Answerer` interface |
| Retuning degrades answers silently | Medium | High | P4.3 baseline + tolerance gates before merging P3.x |
| Behavior drift during refactors | Medium | Medium | Characterization tests (P4.2) before P2.x |
| COM changes can't be tested without Office | High | Medium | Mock tests + manual checklist per format |
| Re-indexing required after chunking/metadata changes | High | Low–Med | `index_version` in doc meta; rebuild on mismatch |
| Streamlit semantics surprises | Medium | Medium | P1.0c manual test; cache/state tests |
| Scope creep into a rewrite | Medium | High | Principle 1; per-item success metrics; keep Phase 5 gated |

## 9. Success metrics (baseline captured in P4.1/P4.3, targets proposed)
| Metric | Baseline (to measure) | Target direction |
|---|---|---|
| Chat input tokens/question (p50/p95) | ≈10k (ESTIMATE) | ↓ ≥60% with quality within tolerance |
| Chat output tokens/answer | ≈600–1,200 (ESTIMATE) | ↓ ≥40% (concise default) |
| Retrieval recall@k_context / MRR | measure | ≥ baseline |
| Answer faithfulness / correctness rubric | measure | ≥ baseline − 2 pts |
| Follow-up question accuracy | measure | ↑ |
| Summarizer generate() calls & decoder tokens per page | ≈4–5 / ≈540–900 (ESTIMATE) | ↓ ≥30% / ↓ ≥50% |
| Repeat-interaction cost in Streamlit | full re-extract (+OCR) (INFERENCE) | 0 repeat extraction/BART |
| Time to first visible summary/answer | measure | ↓ (animation removed, caching) |
| Install reproducibility | none | clean-venv install + smoke test green in CI |
| Test coverage | 0 | all routes + core helpers; CI green |
| Security checks | 0 tests | XSS/path-traversal/size-limit tests pass |
