# MetaPDF — Architecture Reference (Phase 1: understanding only)

Investigated 2026-10-01 at commit `1cea586`. Tags: **FACT** = verified in source; **GRAPH** = from Graphify
(`graphify-out/graph.json`, AST-only, 100% EXTRACTED edges); **INFERENCE**; **UNCERTAINTY**.
No application code was modified. No modernization recommendations here (by design).

## 0. How this was produced (method)
- GRAPH: `graphify query/explain` (with `--context call`) located all relevant files/functions first.
- FACT: only files the graph pointed to were then read: `app.py`, `App/*.py`, `App/streamlit_app/stream_app.py`,
  `requirements.txt`; templates/.gitignore were grepped, not read in full.
- No pre-existing `dev_docs/` or audit docs existed. Existing `CLAUDE.md` only holds Graphify rules.
- Not read: CSS, JS (`static/js/splash.js`), images, `README.md` body, `templates/*.html` bodies beyond grep.
- Graph limits: 116 nodes / 162 edges; cannot see runtime behaviour, config values, or dynamic dispatch.
  Graph contains README heading nodes (noise) and external-library nodes.

## 1. Overview
MetaPDF is a Flask web app (root `app.py`) with three feature areas reached from a home page:
1. **AI chat with PDF** (RAG) — Flask blueprint `App/chat_app.py`, served at `/chat/`.
2. **PDF summarization** — a *separate Streamlit app* `App/streamlit_app/stream_app.py` (local BART model), reached by a Flask redirect to `http://localhost:8501`.
3. **Document→PDF converters** — Flask blueprints for docx/pptx/xlsx/txt under `/docx /ppt /xl /txt`.

FACT: Flask and Streamlit are two independent processes. Nothing in Flask starts Streamlit.

## 2. Repository structure (FACT, git-tracked)
```
app.py                       Flask entry; registers all blueprints
App/home.py                  home_bp: /, /home, /convertor
App/chat_app.py              chat_app bp (url_prefix=/chat): upload + RAG chat
App/streamlit_embed.py       streamlit_bp: /streamlit -> redirect localhost:8501
App/streamlit_app/stream_app.py   Streamlit summarizer (standalone)
App/docx_converter.py        /docx   (Word COM)
App/ppt_converter.py         /ppt    (PowerPoint COM via comtypes)
App/xl_converter.py          /xl     (Excel COM)
App/txt.py                   /txt    (reportlab)
templates/*.html             chat, convertor, docx, home, ppt, splash, txt, xl (ROOT templates dir)
static/{css,js,uploads}      css per page; js/splash.js; sample uploads committed
instance/faiss_index/        COMMITTED index.faiss + index.pkl (see UNCERTAINTY U1)
requirements.txt             17 unpinned deps
```
FACT: blueprints pass `template_folder='templates'` (relative to `App/`), but templates actually live in root `templates/`; they resolve via the app-level template folder.
FACT: `.gitignore` ignores `data/`, `env/`, `*.env`, `__pycache__`, `.streamlit/`. Converters' `static/uploads` and `static/pdfs` are NOT ignored (sample files are committed).

## 3. Entry points & wiring
- FACT `app.py`: `load_dotenv()`; `Flask(__name__)`; `CORS(app)` (all routes, all origins); `secret_key = FLASK_SECRET_KEY` (raises ValueError if unset);
  `UPLOAD_FOLDER = <cwd>/data/Uploads` (created). Registers: `home_bp`, `chat_app` (prefix from blueprint = `/chat`), `docx` `/docx`, `ppt` `/ppt`, `xl` `/xl`, `txt` `/txt`, `streamlit_bp`. `app.run(debug=True)` under `__main__`.
- GRAPH+FACT: `app.py` imports_from `chat_app.py, home.py, docx_converter.py, ppt_converter.py, xl_converter.py, txt.py, streamlit_embed.py`.
- Streamlit entry runs separately on port 8501 (inferred command `streamlit run App/streamlit_app/stream_app.py`; INFERENCE, README not read).

### Route table (FACT)
| Route | Handler | Notes |
|---|---|---|
| `/` | `home.splash` | splash.html |
| `/home` | `home.main_home` | home.html (links to streamlit, chat, convertor) |
| `/convertor` | `home.convertor` | convertor.html (links to 4 converters) |
| `/streamlit` | `streamlit_embed.streamlit_app` | 302 → `http://localhost:8501` (hardcoded) |
| `/chat/` GET/POST | `chat_app.index` | GET renders chat.html; POST upload OR question |
| `/chat/uploads/<filename>` | `uploaded_file` | serves `config['UPLOAD_FOLDER']` (no caller found) |
| `/{docx,ppt,xl,txt}/` | `index` | page |
| `/{…}/upload` POST | `upload_file` | field name `file` |
| `/{…}/static/pdfs/<filename>` | `download_pdf` | serves `static/pdfs` |

## 4. Frontend ↔ backend (FACT, from grep of templates)
- `chat.html` (inline JS): `fetch('/chat/', POST, FormData)` — upload form sends `pdf_files` (L133); question sends `user_question` (L190-193).
- `docx.html`/`ppt.html`/`xl.html`/`txt.html`: `fetch('/<x>/upload', POST, FormData{file})`; response JSON `pdf_url` or `error`.
- `home.html` links use `url_for('streamlit_bp.streamlit_app' | 'chat_app.index' | 'home.convertor')`.
- `convertor.html` links to `ppt_converter.index`, `docx_converter.index`, `xl_converter.index`, `txt_converter.index`.
- Server-rendered Jinja + vanilla JS; no SPA framework observed.
- UNCERTAINTY U6: static image paths use both `images/` and `Images/` (case mismatch; matters on case-sensitive FS); image files not inspected.

## 5. Workflow traces

### W1. PDF Chat (RAG) — `App/chat_app.py`
**Upload:** User selects PDF(s) in chat.html → `POST /chat/` (`pdf_files`) → `index()` (L113) → `allowed_file()` (L33, `.pdf` ext only) →
`get_pdf_text([file])` (L37, PyPDF2 `PdfReader.extract_text()`, concatenated with no separators, per-file exceptions printed & swallowed) →
`get_text_chunks()` (L48, `RecursiveCharacterTextSplitter(chunk_size=10000, chunk_overlap=1000)`) →
`get_vector_store()` (L57): `GoogleGenerativeAIEmbeddings("models/embedding-001")` (Google API) → `FAISS.from_texts` → `save_local(<app.root_path>/data/faiss_index)` →
`session['vector_store_created']=True` → JSON `{status:'success'}`.

**Question:** `POST /chat/` (`user_question`) → requires `session['vector_store_created']` → `load_vector_store()` (L73, `FAISS.load_local(..., allow_dangerous_deserialization=True)`) →
`vector_store.similarity_search(q)` (L159, k not set in code; library default, believed 4 — UNCERTAINTY U3) →
`get_conversational_chain()` (L83): `ChatGoogleGenerativeAI("models/gemini-1.5-flash-8b-001", temperature=0.3)` + `PromptTemplate(context, question)` + `load_qa_chain(chain_type="stuff")` →
`chain({'input_documents': docs, 'question': q})` → `output_text` → appended to `session['chat_history']` (`{question, answer}`) → JSON `{status, answer}`.

**Prompt (FACT, L84-100):** formal/detailed answer from context; if info absent must say "This specific information is not available in the provided context." then answer from general knowledge (so answers may mix non-document knowledge).

**Data/state:** index on disk (global), flag + history in Flask session cookie. GET `/chat/` renders `session['chat_history']`.

GRAPH: `index()` calls `allowed_file, get_pdf_text, get_text_chunks, get_vector_store, load_vector_store, get_conversational_chain` (call lines 129/131/132/133/151/162).

Trace: `User PDF → chat.html fetch → index() → PyPDF2 → splitter → Google embedding API → FAISS file → (question) → FAISS similarity → Gemini via stuff chain → JSON → session history → UI`.

### W2. PDF Summarization — `App/streamlit_app/stream_app.py` (separate process)
User opens `/streamlit` (Flask redirect) → Streamlit UI `st.file_uploader(type="pdf")` → `extract_pages()` (L73; PyPDF2 per page, whitespace-normalised; per-page error placeholder string) →
user chooses page mode (all / comma list / range) and quality slider (Fast 100/30, Balanced 150/50, High 200/75 max/min length) →
button → per page: `generate_smart_summary()` (L126) → `load_model()` (L51, `@st.cache_resource`, **`facebook/bart-large-cnn`** via transformers `AutoTokenizer/AutoModelForSeq2SeqLM` + `pipeline("summarization")`; fp16 on CUDA else CPU) →
`preprocess_text()` (L93: strip whitespace, remove `\d+ of \d+` and URLs, sentence-split, group into <1000-char chunks) → per chunk (skip <15 words) `summarizer(..., num_beams=4, do_sample=False, length_penalty=1.5, early_stopping=True)` → join; if >1 chunk and result > max_length words, a second-pass summarization →
`typewriter_effect()` (char-by-char render, sleep 0.01s, `html.escape`d) + per-page download button; "combined summary" = concatenation of page summaries (NOT re-summarized), optional checkbox/download.

GRAPH: `generate_smart_summary` → `load_model`, `preprocess_text`; `load_model` references `cache_resource`.

Notes (FACT): dynamic length rules by word count (<100 words, >500 words); metrics checkbox (compression %); no network LLM — model weights downloaded from Hugging Face on first run; no OCR (scanned PDFs → empty-text error message). Summaries are per-page; nothing persisted.

Trace: `User PDF → st.file_uploader → extract_pages (PyPDF2) → page select → generate_smart_summary → preprocess_text → BART pipeline (local) → typewriter UI + .txt download`.

### W3. Document conversion (4 blueprints, same shape)
User picks file in `<x>.html` → `POST /<x>/upload` (`file`) → `upload_file()` → extension check → save to `static/uploads/<name>` (cwd-relative) → convert → `static/pdfs/<name>.pdf` → JSON `{pdf_url: '/static/pdfs/<name>.pdf'}` → client loads URL served by `download_pdf` (`send_from_directory`).

| Module | Accepts | Saved name | Converter | Notes (FACT) |
|---|---|---|---|---|
| docx_converter | `.docx` (case-sensitive `endswith`) | original filename (unsanitised) | `win32com Word.Application`, `SaveAs(FileFormat=17)`; `kill_word_processes()` terminates **all** WINWORD.EXE first | input file kept |
| ppt_converter | `.ppt/.pptx` (case-insens.) | `uuid4_<secure_filename>` | `comtypes CreateObject("PowerPoint.Application")`, `Visible=True`, `SaveAs(FileFormat=32)`; kills all `powerpnt.exe` | only module using `secure_filename`, uuid, logging; deletes upload in `finally`; missing/empty-file errors returned without 4xx status |
| xl_converter | `.xlsx` | original filename | `win32com Excel.Application`, `ExportAsFixedFormat(0, …)`; kills all `EXCEL.EXE` | input kept |
| txt | `.txt` | original filename | reportlab canvas (Helvetica 12, letter, margin 40, manual word-wrap, new page on overflow), UTF-8 read | pure Python; portable |

GRAPH call edges: `upload_file → convert_*`, `convert_docx/ppt/excel → kill_*_processes`, `upload_file → allowed_file` (ppt only).
INFERENCE: Word/PowerPoint/Excel converters require Windows + installed MS Office (pywin32/comtypes/pythoncom imports at module top; `app.py` imports them unconditionally, so the whole Flask app only imports where these packages exist).
FACT: `pythoncom.CoUninitialize()` is skipped on exception paths in docx/ppt/xl.

## 6. External services / models
| Service | Used by | Config |
|---|---|---|
| Google Generative AI embeddings `models/embedding-001` | chat upload + load | `GOOGLE_API_KEY` |
| Google Gemini chat `models/gemini-1.5-flash-8b-001`, temp 0.3 | chat answer | `GOOGLE_API_KEY` |
| Hugging Face `facebook/bart-large-cnn` (local inference) | Streamlit summarizer | none; downloads on first load |
| MS Word/PowerPoint/Excel via COM | converters | local Office install |

FACT: `chat_app.py` calls `genai.configure(api_key=...)`; the LangChain Google classes are constructed without an explicit key (INFERENCE: they read `GOOGLE_API_KEY` from env).

## 7. Configuration & env (FACT)
- `FLASK_SECRET_KEY` (required, `app.py`, via `load_dotenv()` default search).
- `GOOGLE_API_KEY` (required at import of `chat_app.py`, else ValueError → **whole Flask app fails to start**). Loaded from `<cwd>/env/.env` (explicit path) — a *different* location than `app.py`'s default `.env` lookup. `env/` is gitignored, so the real file layout is UNCERTAIN (U5).
- Paths are cwd-relative (`static/uploads`, `static/pdfs`, `data/Uploads`, `env/.env`) except the FAISS path which is `app.root_path/data`.
- `requirements.txt`: unpinned; includes `chromadb` (not imported anywhere in tracked .py) and `requests` (not imported); `streamlit` and `torch` are **not listed** though `stream_app.py` imports them. Legacy `langchain.*` imports (`text_splitter`, `chains.question_answering`, `prompts`).

## 8. State, caching, persistence
- Flask session (signed cookie): `chat_history` (list of Q/A), `vector_store_created`.
- FAISS index on disk, single global location, overwritten by each successful upload (FACT); no per-user isolation (INFERENCE: one user's upload replaces another's; every session with the flag queries the latest index).
- Streamlit: `st.cache_resource` caches the model; no explicit session_state.
- No DB. No HTTP caching logic. Converter uploads/outputs persist in `static/`.

## 9. Error handling (FACT)
- chat: outer `try/except Exception` returns `{status:'error', message: str(e)}` (HTTP 200; exposes exception text); helpers `print()` and swallow errors; blueprint `errorhandler(413)`/`(500)` return JSON. No `MAX_CONTENT_LENGTH` set in `app.py`, so 413 is not produced by config.
- converters: JSON `{error}` with 400/500; `print` logging (logging module in ppt).
- streamlit: `st.error`/`st.warning`; broad `except` with silent `continue`/`pass` in summarization.

## 10. Architectural observations (non-prescriptive)
1. Chat upload loop returns on the first valid PDF; other files in the same request are ignored.
2. Chat answers are not guaranteed grounded: prompt authorises fallback to general knowledge.
3. `allow_dangerous_deserialization=True` on FAISS load (pickle) of a locally written index.
4. Converters terminate *all* running Office processes of that type system-wide before converting.
5. docx/xl/txt save with client-supplied `file.filename` unsanitised; ppt uses `secure_filename`.
6. Two vector-data locations exist: code path `data/faiss_index` (gitignored) vs committed `instance/faiss_index` (U1).
7. Summarizer stack (Streamlit + torch + transformers) is operationally independent of Flask; `/streamlit` hardcodes `localhost:8501`.
8. Two different PDF-text extraction/cleanup paths exist (chat: raw concatenation; summarizer: per-page, regex-cleaned).

## 11. Uncertainties (open)
- U1: `instance/faiss_index/{index.faiss,index.pkl}` committed but no code references `instance/`; code writes `app.root_path/data/faiss_index`. Likely stale artifact (INFERENCE). Not inspected (pickle not loaded deliberately).
- U2: Exact startup commands/ports for Streamlit (README not read this phase).
- U3: `similarity_search` default k at installed version.
- U4: Whether legacy `langchain.*` imports work at the version resolved from unpinned requirements; nothing was run.
- U5: Real `.env` layout (`env/.env` vs root `.env`).
- U6: Static image directories/case (`images/` vs `Images/`); image assets not inspected.
- U7: `chat.html` client logic beyond fetch calls (history rendering, error UI); `splash.js`.
- U8: Nothing was executed — no runtime verification of any workflow.
- U9: README claims vs code not compared.

## 12. Graphify assets
Graph: `graphify-out/graph.json` (built from commit `1cea5863`; re-run `graphify update .` after code changes; git hooks installed).
Communities: README, chat_app, docx_converter(+xl), stream_app, app(+home, streamlit_embed), ppt_converter, txt.
Graph limits: xl_converter nodes cluster into the docx_converter community; AST-only, so it has no env keys, model names, prompts or numeric parameters — those come from source.
Query recipes: see KNOWLEDGE_BASE.md.
