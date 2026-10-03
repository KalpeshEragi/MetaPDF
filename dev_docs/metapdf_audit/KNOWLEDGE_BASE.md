# MetaPDF — Knowledge Base (concise reusable facts)
Details and traces: `01_architecture.md`. Verified 2026-10-01 @ `1cea586`. [F]=source-verified, [G]=Graphify, [I]=inference, [?]=unverified.

## Where to look (don't rescan)
- RAG chat → `App/chat_app.py` only (+ `templates/chat.html` inline JS) [F][G]
- Summarizer → `App/streamlit_app/stream_app.py` (separate Streamlit process) [F]
- Converters → `App/{docx_converter,ppt_converter,xl_converter,txt}.py` [F]
- Wiring/config → `app.py`; pages → `App/home.py`; redirect → `App/streamlit_embed.py` [F]
- Templates are in ROOT `templates/`, static in ROOT `static/` [F]

## Models & services
- Embeddings: Google `models/embedding-001`; chat LLM: `models/gemini-1.5-flash-8b-001`, temp 0.3; key `GOOGLE_API_KEY` [F]
- Summarizer: local `facebook/bart-large-cnn`, fp16 on CUDA, beam 4, `st.cache_resource` [F]
- Vector store: FAISS (faiss-cpu) via langchain_community; saved to `<app.root_path>/data/faiss_index` [F]
- Chunking (chat): RecursiveCharacterTextSplitter 10000/1000. Chunking (summary): regex sentence groups <1000 chars [F]
- Retrieval: `similarity_search(q)` with default k (not set in code) → "stuff" QA chain [F]; k=4 assumed [?]
- Parsing: PyPDF2 in both chat and summarizer; no OCR [F]

## Env / config
- Required: `FLASK_SECRET_KEY`, `GOOGLE_API_KEY` (import-time ValueError in app.py / chat_app.py) [F]
- chat_app loads `<cwd>/env/.env`; app.py uses default `.env` search [F]
- No `MAX_CONTENT_LENGTH`; CORS open to all; `debug=True` [F]
- `requirements.txt` unpinned; lacks streamlit/torch; lists unused chromadb, requests [F]

## Endpoints
`/`, `/home`, `/convertor`, `/streamlit` (→ localhost:8501), `/chat/` (POST: `pdf_files` | `user_question`), `/{docx,ppt,xl,txt}/upload` (POST `file`) → JSON `pdf_url` under `/static/pdfs/` [F]

## State
Flask session: `chat_history`, `vector_store_created`. One global FAISS index shared by all users, overwritten per upload [F]. No DB.

## Behaviours worth remembering
- Chat upload handles only the first valid PDF per request [F]
- Chat prompt allows fallback to general knowledge when context lacks the answer [F]
- Chat errors return HTTP 200 JSON with raw exception text [F]
- docx/xl/ppt converters need Windows + MS Office (COM) and kill ALL Word/Excel/PowerPoint processes before converting; txt uses reportlab (portable) [F]
- Only ppt uses `secure_filename` + uuid and deletes the upload; docx/xl/txt use the raw filename and keep files [F]
- Combined summary = concatenation of per-page summaries (no re-summarize) [F]
- Committed `instance/faiss_index/*` not referenced by code (likely stale) [I]; pickle not inspected
- Converter imports are unconditional in `app.py`, so the Flask app can't import without pywin32/comtypes [I]

## Graphify usage (works well)
```
export PATH="$PATH:/c/Users/kalpesh/AppData/Roaming/Python/Python313/Scripts"   # graphify.exe is not on PATH by default
graphify query "<question>" --context call --budget 1500   # call edges only, less noise
graphify explain "<function()>"    graphify path "A" "B"    graphify affected "X"    graphify god-nodes
graphify update .                  # after code changes; AST-only, no API cost
```
Graph = 116 nodes / 162 edges, all EXTRACTED. Good for file/function/call discovery; blind to config values, prompts, model names, runtime behaviour, so read source for those. README headings add noise nodes.

## Open questions
See 01_architecture.md §11 (U1–U9). Nothing has been executed at runtime yet.
