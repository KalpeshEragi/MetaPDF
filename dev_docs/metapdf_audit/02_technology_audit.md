# MetaPDF — Technology & Dependency Audit (analysis only)

Audited 2026-10-03 at commit `1cea586`. No code was changed; nothing was run or installed.
Builds on `01_architecture.md` and `KNOWLEDGE_BASE.md` (read first for workflows).

Tags: **FACT** = verified in this repo's source; **GRAPH** = Graphify import/call edges; **KNOWLEDGE** = my background knowledge of
upstream libraries/services, *not* verified online or at runtime in this audit (re-check before acting); **UNCERTAIN**.

## 0. Method & limits
- GRAPH: `graph.json` import edges per file (extracted programmatically), cross-checked against a grep of every `import` line (FACT: both agree) and an AST pass for unused imports.
- FACT: `requirements.txt` was compared against what source actually imports, not trusted.
- Limit: the Python on this machine (3.13.7) is **not the project's environment**: Flask, langchain*, faiss, streamlit, PyPDF2 are not installed there; `pypdf 6.19`, `google-generativeai 0.8.6`, `torch 2.9.1`, `transformers 5.0.0`, `psutil 7.1.3`, `pywin32 311`, `requests 2.32.2`, `python-dotenv 1.0.1` are. So **installed/resolved versions of the app's real stack are unknown** (UNCERTAIN) and nothing about compatibility was tested.
- Limit: upstream deprecation/EOL statements below come from KNOWLEDGE and must be confirmed against current docs.

## 1. Current technology stack (FACT unless noted)
| Layer | Technology | Where |
|---|---|---|
| Language | Python (version not pinned anywhere) + vanilla HTML/CSS/JS | whole repo |
| Web backend | Flask, blueprints, Jinja2 templates, signed-cookie sessions, flask-cors | `app.py`, `App/*.py` |
| Second web framework | Streamlit (separate process, port 8501) | `App/streamlit_app/stream_app.py` |
| Frontend | Server-rendered Jinja + hand-written JS (751 lines HTML total, 10-line `splash.js`); no bundler, no JS framework, no package.json | `templates/`, `static/` |
| Frontend external assets | Google Fonts (Roboto, Poppins) in splash/home; Font Awesome 6.0.0 from cdnjs in chat.html | templates |
| LLM/RAG | LangChain (legacy API) + Google Gemini + Google embeddings + FAISS | `App/chat_app.py` |
| Local ML | Hugging Face `facebook/bart-large-cnn` via transformers + torch | `stream_app.py` |
| PDF text | PyPDF2 | chat_app, stream_app |
| Office→PDF | MS Office COM automation (pywin32 `win32com`, comtypes, pythoncom) | docx/ppt/xl converters |
| TXT→PDF | reportlab | `App/txt.py` |
| Infra helpers | python-dotenv, psutil, werkzeug (`secure_filename`) | various |
| Persistence | Local filesystem only; no database | FAISS dir, `static/uploads`, `static/pdfs` |
| Auth / users | None (a Flask secret key for sessions only) | `app.py` |
| Tests / CI / packaging / Docker | **None found** (no tests, Dockerfile, CI config, lockfile, pyproject in tracked files) | repo root |

## 2. Dependency inventory (requirements.txt vs. reality)
`requirements.txt` has 17 unpinned entries and omits some real dependencies.

| # | requirements.txt entry | Imported in source? | Where / why it exists | Active? | Notes |
|---|---|---|---|---|---|
| 1 | `google-generativeai` | Yes, `import google.generativeai as genai` | `chat_app.py:5,28` only `genai.configure(api_key=…)` | **Marginal** | Its only use is configure(); the LangChain wrapper does the actual calls. KNOWLEDGE: this SDK is the legacy Google package, superseded by `google-genai`. |
| 2 | `python-dotenv` | Yes | `app.py:14`, `chat_app.py:22` | Active | Loaded twice from two different locations (`.env` default vs `<cwd>/env/.env`) |
| 3 | `langchain-community` | Yes (`FAISS`) | `chat_app.py:6` | Active | Only for the FAISS wrapper |
| 4 | `langchain` | Yes (`text_splitter`, `chains.question_answering`, `prompts`) | `chat_app.py:4,8,9` | Active | All three are legacy import paths (see §5) |
| 5 | `PyPDF2` | Yes | `chat_app.py:3`, `stream_app.py:3` | Active (2 call sites) | KNOWLEDGE: PyPDF2 is deprecated/archived; `pypdf` is the continuation. |
| 6 | `chromadb` | **No** | nowhere (FACT, grep + graph) | **Dead** | Heavy dependency tree; looks like a leftover from an earlier vector-store choice (INFERENCE) |
| 7 | `faiss-cpu` | Indirect (via `langchain_community.vectorstores.FAISS`) | index build/load | Active | Not imported directly; version must match what langchain-community expects |
| 8 | `langchain_google_genai` | Yes | `chat_app.py:7` (embeddings + chat) | Active | The real LLM/embedding path |
| 9 | `flask` | Yes | everything | Active | |
| 10 | `pywin32` | Yes (`pythoncom`, `win32com`) | docx, xl, ppt (pythoncom) | Active, Windows-only | |
| 11 | `psutil` | Yes | docx, xl, ppt `kill_*_processes` | Active | Used only to terminate Office processes |
| 12 | `comtypes` | Yes | `ppt_converter.py:4` only | Active (one file) | **Overlaps pywin32**: both do COM automation |
| 13 | `werkzeug` | Yes | `secure_filename` in ppt_converter (chat_app import unused) | Active, transitive anyway | Pulled in by Flask |
| 14 | `reportlab` | Yes | `txt.py` | Active | |
| 15 | `transformers` | Yes | `stream_app.py` | Active | Only for BART summarization |
| 16 | `requests` | **No** | nowhere | **Dead** (maybe transitive) | |
| 17 | `flask-cors` | Yes | `app.py:4,18` | Active | Enabled for ALL origins and routes |
| — | `streamlit` | Yes, but **missing from requirements.txt** | stream_app | Active | Undeclared |
| — | `torch` | Yes, **missing** | stream_app | Active | Undeclared; huge, CUDA-variant-sensitive |
| — | `langchain-text-splitters`, `langchain-core` | not directly | transitive of langchain | — | |
| — | stdlib (`os,re,time,html,logging,uuid`) | — | — | — | fine |

Counts (FACT): 2 dead (chromadb, requests); 2 undeclared (streamlit, torch); 1 near-dead (google-generativeai).

## 3. AI / ML stack
### 3.1 LLM providers
- FACT: exactly **one** hosted LLM provider: Google Gemini (`models/gemini-1.5-flash-8b-001`, temp 0.3) via `langchain_google_genai.ChatGoogleGenerativeAI`.
- FACT: **no** Ollama, OpenAI, Anthropic, or other provider code anywhere (grep over .py/.html/.js).
- FACT: one local model: `facebook/bart-large-cnn` (summarization only, no chat).
- Result: two unrelated AI pathways that share nothing (different libs, different PDF cleaning, different chunking, different UIs) — see §4.

### 3.2 Embeddings / vector store / retrieval
- Embeddings: Google `models/embedding-001` (network call per upload and per question-time load; queries embedded via the same class).
- Vector store: FAISS via LangChain, persisted with pickle (`allow_dangerous_deserialization=True`). `chromadb` listed but never used.
- Retrieval: plain `similarity_search(q)` — no metadata, no MMR/score threshold, no re-ranking, no per-document partition.
- Chunking: character-based 10000/1000 (very large chunks; with default k the "stuff" chain sends large context).
- LangChain usage is shallow: splitter, prompt template, `load_qa_chain("stuff")`, FAISS wrapper. No agents, memory, LCEL, or retrievers. (FACT)

### 3.3 Summarization
- FACT: BART via `pipeline("summarization")`, hand-rolled regex preprocessing, chunking by 1000 chars, second-pass summarization, typewriter UI.
- It does **not** use the Gemini path or LangChain. It has its own PDF extractor (`extract_pages`) separate from chat's `get_pdf_text` (duplicate extraction logic).
- UNCERTAIN/KNOWLEDGE: `transformers 5.0.0` is what's installed on this machine; whether the `"summarization"` pipeline task and `.half()` flow work unchanged on v5 is untested here. BART-large-CNN is a news-trained model with a ~1024-token input limit; the 1000-char chunking keeps within it (FACT of code; limit is KNOWLEDGE).

## 4. Redundancy / overlap analysis
| Area | Competing pieces | Verdict |
|---|---|---|
| COM automation | `pywin32` (`win32com`) in docx+xl, `comtypes` in ppt | Same job, two libs. `pythoncom` (from pywin32) is used in all three anyway, so comtypes is the removable one in principle (INFERENCE, untested). |
| Web frameworks | Flask + Streamlit | Two servers, two processes, hard-coded redirect; summarizer UI is not integrated into Flask styling/session. |
| AI paths | Gemini API (chat) vs local BART (summary) | No shared abstraction; different cost, latency, privacy profiles (chat sends document text to Google; summary stays local — FACT). |
| PDF text extraction | Two separate PyPDF2 call sites with different cleaning | Duplicated logic. |
| Google SDKs | `google-generativeai` + `langchain_google_genai` | Both installed; only the latter does the work. |
| Vector store | `faiss-cpu` (used) + `chromadb` (unused) | Dead duplicate. |
| Upload/convert handlers | docx/ppt/xl/txt `upload_file` are four near-copies (same route shape, same response JSON) with inconsistent validation (§6) | Copy-paste duplication. |
| Env loading | `load_dotenv()` in app.py plus `load_dotenv(<cwd>/env/.env)` in chat_app | Two conflicting locations. |

## 5. Technical debt (FACT unless tagged)
1. **Unused imports** (AST-verified): `chat_app.py`: `secure_filename`, `url_for`, `uuid`; `home.py`: `os`, `send_from_directory`; `ppt_converter.py`, `txt.py`, `xl_converter.py`: `Flask`; `streamlit_embed.py`: `render_template`.
2. **Dead code / leftovers:** `uploaded_file()` route in chat (`/chat/uploads/<f>`) uses `UPLOAD_FOLDER` but the chat flow never saves files; `app.config["UPLOAD_FOLDER"]` / `data/Uploads` created at startup for it. Commented-out code in `home.py` and `stream_app.py` (e.g. footer, "RTX 2050" notes). `typewriter_effect` embeds a `<script>` via `st.markdown`, likely inert in Streamlit (INFERENCE, untested).
3. **Legacy LangChain API** (KNOWLEDGE): `load_qa_chain` and `langchain.chains.*` are deprecated since LangChain 0.2 and removed from the main `langchain` package in v1.0 (moved to `langchain-classic`); `langchain.text_splitter` / `langchain.prompts` are now re-homed in `langchain-text-splitters` / `langchain-core`. With unpinned requirements, a fresh install may break `chat_app.py` at import (UNCERTAIN — not tested).
4. **Retired / aging model IDs** (KNOWLEDGE): Gemini 1.5 family models and `embedding-001` were scheduled for retirement by Google; hard-coded IDs in `chat_app.py:61,77,102` could fail at runtime. Needs confirmation against Google's current model lifecycle page.
5. **Env/config:** two `.env` locations; import-time hard failure if `GOOGLE_API_KEY` missing (blocks unrelated routes like converters); no config object; hard-coded model names, chunk sizes, port 8501, `debug=True`.
6. **Path handling:** cwd-relative paths (`static/uploads`, `static/pdfs`, `env/.env`, `data/Uploads`) vs `app.root_path` for FAISS — behavior depends on launch directory.
7. **Case-sensitivity bug (resolves earlier U6):** git tracks `static/Images/` (capital I) but `home.html`, `ppt.html`, `txt.html`, `xl.html` reference `images/…` while `convertor.html`/`docx.html` use `Images/…`. Works on Windows/macOS default filesystems; would break on Linux for the lowercase references.
8. **Binary/sample data committed:** sample uploads in `static/uploads/`, screenshot PNGs/`.jfif` in `static/Images/`, a pickled FAISS index in `instance/faiss_index/` (stale; unreferenced by code).
9. **No tests, no CI, no lockfile, no Python version, no Dockerfile, no README run instructions verified** (README not audited).
10. **Frontend:** every dynamic message is injected through `innerHTML` (`chat.html:108,178,204`), including the user's own question (L180) and the model's answer typed char-by-char (L108) with no escaping.
11. **Windows-only core:** `app.py` imports docx/ppt/xl converters unconditionally; `pythoncom`/`win32com`/`comtypes` imports fail off Windows, so the entire Flask app (including chat) cannot start on Linux/macOS/containers (INFERENCE from import structure).

## 6. Risks
### Security (FACT-based unless tagged)
- **Stored/reflected XSS surface in chat UI:** user text and LLM output rendered via `innerHTML` (§5.10). LLM output is influenced by uploaded PDF content (prompt-injection → script injection path) (INFERENCE).
- **Unsanitised filenames** in docx/xl/txt: `os.path.join(UPLOAD_FOLDER, file.filename)` with the client-supplied name → path traversal / overwrite risk (werkzeug typically strips nothing here; behavior of Flask's `FileStorage.filename` is raw). Only ppt uses `secure_filename`.
- **`allow_dangerous_deserialization=True`:** FAISS metadata is a pickle; safe only while the index file is trusted. The index sits on disk at a fixed path (no upload path to it observed, but the committed `instance/faiss_index/index.pkl` shows pickles are also in git).
- **CORS `*` + `debug=True`:** `CORS(app)` allows all origins on all routes, and `app.run(debug=True)` enables the Werkzeug debugger (remote code execution if exposed beyond localhost).
- **No auth, no per-user isolation:** one shared FAISS index and one shared converter output folder (`static/pdfs/` is publicly served; converted documents are reachable by guessable names for docx/xl/txt).
- **No upload size limit** (`MAX_CONTENT_LENGTH` unset), no rate limiting; chat endpoint spends Google API quota per request.
- **Error leakage:** raw exception text returned to client (`chat_app.py:184`).
- **Process killing:** converters terminate all Word/Excel/PowerPoint processes system-wide, which can destroy a user's unsaved work on the host (FACT); concurrency unsafe (COM + global kills).
- **Data egress:** chat sends full PDF chunks to Google (embeddings + prompts). Summarizer is local. Documented nowhere in UI (FACT of code; README not checked).
- **Supply chain:** unpinned deps, no lockfile; `torch`/`transformers` pulled from Hugging Face Hub at first run (model download, `bart-large-cnn` not pinned to a revision).

### Maintenance / deployment
- Deployment complexity is high for a small app: Windows + licensed MS Office + (optional) NVIDIA GPU/CUDA torch + Google key + two processes. Dev server only (`app.run`); no WSGI config.
- Vendor lock-in: Google (LLM + embeddings, both through LangChain but with Google-specific classes and `genai`). Embedding model lock-in: changing embedding model requires re-indexing (the stored index has no model metadata, INFERENCE). Microsoft Office lock-in for 3 of 4 converters.
- Heavy installs: `torch` + `transformers` + `chromadb` (unused) + `faiss-cpu` + `streamlit` dominate environment size.

## 7. Dependency-by-dependency verdict (condensed)
| Dependency | Why exists | Used | Overlap | Outdated? | Lock-in | Security/maintenance | Simpler/modern alternative (KNOWLEDGE) |
|---|---|---|---|---|---|---|---|
| Flask | web app | yes | Streamlit | no | low | fine; debug mode risk is config | keep |
| flask-cors | cross-origin | yes (needed? app is same-origin) | — | no | none | `*` too permissive | restrict or remove (same-origin pages) |
| Streamlit | summary UI | yes | Flask | no | medium | second server | fold into Flask endpoint or keep as isolated service |
| LangChain (legacy API) | splitter/prompt/chain/FAISS glue | yes, shallow | direct SDK calls | **yes** (deprecated chain API) | low–medium | breakage on upgrade | LCEL/retriever pattern, or direct SDK + FAISS/numpy for this small use |
| langchain-community | FAISS wrapper | yes | — | moving package | low | — | `langchain-community` FAISS or faiss direct |
| langchain_google_genai | Gemini + embeddings | yes | google-generativeai | current-ish | **Google** | API/model churn | keep or provider-agnostic interface |
| google-generativeai | `genai.configure` | marginal | langchain_google_genai | **legacy SDK** (KNOWLEDGE) | Google | EOL risk | `google-genai` or drop (not needed) |
| faiss-cpu | vector index | yes | chromadb | no | none | pickle persistence | fine for small scale; Chroma/SQLite-vec/pgvector if multi-user |
| chromadb | — | **no** | faiss | n/a | none | heavy, vulnerability surface for nothing | remove |
| PyPDF2 | PDF text | yes | pypdf | **deprecated** (KNOWLEDGE) | none | unmaintained | `pypdf` (drop-in-ish); `pymupdf` for better extraction/layout/OCR hooks |
| transformers + torch | BART summary | yes | Gemini could summarize | version-sensitive | Hugging Face hub | big, GPU-dependent | smaller/modern summarizer or reuse the LLM already configured |
| pywin32 | COM (Word/Excel) | yes | comtypes | no | Windows+Office | kills processes | LibreOffice headless / docx2pdf-style portable pipeline (needs evaluation) |
| comtypes | COM (PowerPoint) | yes (1 file) | pywin32 | no | Windows+Office | same | consolidate on one COM lib |
| psutil | kill Office | yes | — | no | none | process-kill pattern is the risk | avoid by per-job isolation |
| reportlab | TXT→PDF | yes | — | no | none | fine | keep (portable) |
| python-dotenv | env loading | yes | — | no | none | two loaders | one loader |
| requests | — | **no** | — | — | — | — | remove (verify transitive) |
| werkzeug | `secure_filename` | partly | — | transitive | none | — | use consistently |

## 8. Modernization opportunities (not implemented)
1. Declare dependencies truthfully: add `streamlit`, `torch`; remove `chromadb`, `requests`; pin versions + lockfile; record Python version.
2. Remove unused imports/dead route and align `images/` vs `Images/` references.
3. Move the chat stack off deprecated LangChain chain APIs and re-verify Gemini/embedding model IDs; add model names/chunk params to config.
4. Swap/upgrade PyPDF2 → `pypdf` (or PyMuPDF); share one extraction function between chat and summarizer.
5. Consolidate COM libraries; evaluate a portable Office→PDF path to make the app deployable beyond Windows-with-Office; lazy-import converters so chat/summary still start without them.
6. Isolate per-user/per-session state (index per session, not one global folder).
7. Replace `innerHTML` rendering with `textContent`/escaped/sanitised markdown.
8. Decide Flask vs Streamlit boundary (one process or an explicit service with configurable URL).
9. Add basic tests (route smoke tests, chunking, converters with mocks) and a config module.
10. Security hardening: `MAX_CONTENT_LENGTH`, `secure_filename` everywhere, disable debug outside dev, restrict CORS, unique output names.

## 9. Recommended direction (guidance only)
Keep the product shape (Flask front + chat + summarizer + converters). Highest value-for-effort order: (a) make the environment reproducible and truthful (deps, config, lockfile) → (b) fix the correctness/security items that don't change behaviour (filenames, XSS, debug/CORS, size limit, image paths) → (c) isolate state per session → (d) modernize the RAG layer and PDF library → (e) decide on the cross-platform converter strategy and the Flask/Streamlit boundary. Treat provider choice (Gemini vs local) as a product decision to make explicitly rather than by default.

## 10. Open items to verify next (UNCERTAIN)
- Create the project's real venv and record **resolved** versions (the stack's actual installed versions are unknown).
- Whether `chat_app.py` imports cleanly on current LangChain, and whether `gemini-1.5-flash-8b-001` / `embedding-001` still respond for the user's key.
- Whether `transformers 5.x` still supports the `"summarization"` pipeline as used.
- Whether `requests`/`chromadb` are depended on transitively by anything (e.g. langchain) — dead as *direct* deps is verified, necessity is not.
- README claims (features, setup) vs this audit; contents of `.env` layout; real deployment target.
- Streamlit's handling of the injected `<script>`; behavior of `FileStorage.filename` traversal in the installed Werkzeug version.
