# MetaPDF — Baseline Environment Verification

Run 2026-10-04 with `eval/check_environment.py` (raw output: `eval/environment.json`). Production code was **not** modified.
Interpreter: the project's own `C:\AllImpprojects\MetaPDF\venv` (Python 3.13.7), code at `main` @ `6418b77`.
All entries below are **measured**, not estimated. Secrets were loaded from the gitignored `env/.env` into the process only; values are never printed or stored (only key *names* are recorded: `FLASK_SECRET_KEY`, `GOOGLE_API_KEY`).

## 1. Headline: the current system is broken in four independent ways
| # | Component | Status | Exact failure |
|---|---|---|---|
| 1 | Chat module import | **BROKEN** | `import App.chat_app` → `ModuleNotFoundError: No module named 'langchain.text_splitter'`. Also missing: `langchain.chains` (`langchain.chains.question_answering`), `langchain.prompts`. Installed `langchain 1.3.18` removed these paths. Because `app.py` imports `chat_app` at top level, **the whole Flask app fails to start** (inference from the import chain; `app.py` itself was not launched in this check). |
| 2 | Embedding model | **BROKEN** | `models/embedding-001` → `404 NOT_FOUND … not found for API version v1beta, or is not supported for embedContent`. Model listing contains only `gemini-embedding-001`, `gemini-embedding-2`, `gemini-embedding-2-preview`. |
| 3 | Chat LLM | **BROKEN** | `models/gemini-1.5-flash-8b-001` → `404 NOT_FOUND … not supported for generateContent`. Listing has 61 models; none is the 1.5 family (currently listed flash-class: `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.x-flash*`, `gemini-flash-latest`, `gemini-flash-lite-latest`, …). |
| 4 | OCR fallback | **BROKEN** | `pdf2image` → `PDFInfoNotInstalledError: Unable to get page count. Is poppler installed and in PATH?` (`pdftoppm` not found). EasyOCR imports and its English weights are cached, but the rasterization step in `ocr_processor.hybrid_extract_pages` fails; that function catches the error and prints `OCR fallback failed`, returning blank text for scanned pages (FACT from source; failure itself reproduced with `pdf2image`). |
| 5 | BART summarizer | **BROKEN** | After the (approved) weights download, production `load_model()` fails: `Error loading model: "Unknown task summarization, available tasks are ['any-to-any', 'audio-classification', ...]"` — the `summarization` pipeline task no longer exists in `transformers 5.16.1`. `load_model` catches the exception, returns `None`, and `generate_smart_summary()` then returns `""` for every page: the shipped UI would show empty summaries ("Could not generate summaries for the selected pages"). Measured with `eval/run_summarization_baseline.py` (field `_as_shipped`). Also: `torch 2.13.0+cpu` in the venv, so even when fixed the model runs on **CPU** (RTX 2050 unused). |

Consequence: with the system "as configured", PDF chat produces **zero answers** (it cannot start, and even if the imports were repaired it cannot embed or generate) and the summarizer produces **empty summaries**. Only the document converters and static pages were not examined here (out of scope for the LLM baseline).

## 2. Environment
| Item | Value |
|---|---|
| OS | Windows 11 Home (10.0.26200) |
| CPU | Intel64 Family 6 Model 154 (12 logical cores); RAM 16.9 GB |
| GPU | NVIDIA GeForce RTX 2050, 4096 MiB, driver 577.00 |
| PyTorch | `2.13.0+cpu` in the project venv → **`torch.cuda.is_available() == False`**: the summarizer would run on **CPU** despite the GPU (the code path uses `.half().to("cuda")` only if CUDA is available). |
| Python | 3.13.7 (`venv/pyvenv.cfg`) |

### Package versions (resolved in the project venv)
| Package | Version | Note |
|---|---|---|
| Flask / flask-cors | 3.1.3 / 6.0.5 | |
| langchain | **1.3.18** | legacy `text_splitter`/`chains`/`prompts` removed |
| langchain-classic | 1.0.8 | contains relocated `load_qa_chain` (available, **not used by production code**) |
| langchain-core / -community | 1.6.1 / 0.4.2 | |
| langchain-text-splitters | 1.1.2 | relocated `RecursiveCharacterTextSplitter` (available, not used) |
| langchain-google-genai | 4.4.0 | |
| google-generativeai / google-genai | 0.8.6 / 2.24.0 | |
| faiss-cpu | 1.15.0 | imports OK |
| PyPDF2 / pypdf | 3.0.1 / — | PyPDF2 imports OK |
| streamlit | 1.64.0 | |
| torch / transformers | 2.13.0 (CPU) / 5.16.1 | |
| easyocr / pdf2image / Pillow / numpy | 1.7.2 / 1.17.0 / 12.3.0 / 2.5.2 | |
| chromadb | 1.5.9 | installed but never imported by the app |
| pywin32 / comtypes / psutil / reportlab / python-dotenv | 312 / 1.4.16 / 7.2.2 / 5.0.1 / 1.2.3 | |
(Other interpreter on PATH — global Python 3.13.7 — is *not* the project environment and lacks Flask/LangChain; it was not used.)

## 3. LangChain / FAISS status
- `langchain_community.vectorstores` (FAISS wrapper) imports OK; `faiss-cpu 1.15.0` imports OK.
- `FAISS.similarity_search` default **k = 4** (resolves earlier open question U3 / P1.0f: measured from the installed signature).
- Relocated equivalents exist (`langchain_text_splitters.RecursiveCharacterTextSplitter`, `langchain_classic.chains.question_answering.load_qa_chain`, `langchain_core.prompts.PromptTemplate`) — noted for the owner's decision on how to proceed; **none were used**.

## 4. Gemini availability (live API calls, key present)
| Call | Result | Latency |
|---|---|---|
| `list_models()` | OK (61 models) — neither configured ID is present | 1.3 s |
| `embed_query` with `models/embedding-001` | 404 NOT_FOUND | 1.7 s |
| `invoke` with `models/gemini-1.5-flash-8b-001` | 404 NOT_FOUND | 1.9 s |
These confirm, with evidence, the earlier KNOWLEDGE-tagged suspicion that the hard-coded model IDs are retired.

## 5. Decisions taken for the baseline (recorded so future runs use the identical setup)
The brief: use the current implementation exactly, record failures, never silently replace components or invent results. Therefore:
- **As-shipped status** is reported as the headline result: chat = FAIL at import; summarizer = FAIL at model load (empty output).
- A *comparable* baseline, labeled **`baseline-compat-v1`**, runs the **unmodified production functions** with only these substitutions
  (all implemented in `eval/`, none in production code):
  | Gap | Substitution | Where |
  |---|---|---|
  | removed `langchain.text_splitter`, `langchain.chains.question_answering`, `langchain.prompts` | aliased at import time to the relocated, behaviour-identical `langchain_text_splitters.RecursiveCharacterTextSplitter`, `langchain_classic...load_qa_chain`, `langchain_core.prompts.PromptTemplate` | `eval/compat_shims.py` |
  | retired Gemini LLM `gemini-1.5-flash-8b-001` | **Qwen3.5:4B via Ollama, non-thinking (`think=false`)**, temperature 0.3 (production value), `num_ctx` 16384, seed 42, `num_predict` cap 4096 (safety only) — fixed generator for this and all future experiments (owner decision) | `eval/compat_shims.py` |
  | retired Gemini embeddings `embedding-001` | **bge-m3 via Ollama** (`truncate=false`, `num_ctx` 8192, **`num_batch` 8192**, no task prefixes), fixed embedder for all future experiments | `eval/compat_shims.py` |
  | removed `transformers` `summarization` pipeline | direct `model.generate` equivalent (tokenize without truncation, same generation kwargs, decode) around the unchanged `load_model()`, `preprocess_text()`, `generate_smart_summary()` | `eval/run_summarization_baseline.py` |
- **Embedder choice, with evidence:** the owner first selected `nomic-embed-text`. A direct test showed Ollama caps it at 2,048 tokens (8,000 chars → 1,711 tokens OK; 10,000 chars → HTTP 400 "the input length exceeds the context length", even with `num_ctx` 8192). Production chunks are 10,000 characters, so nomic would either fail or silently embed only a prefix of every chunk, handicapping the baseline for a reason unrelated to MetaPDF's design. After asking, the owner approved **bge-m3** (8,192-token context). Follow-up test: bge-m3 also rejected 10,000-char chunks with Ollama's default `num_batch` (2048; chunk = 2,485 tokens) but works once `num_batch` ≥ 4096, so the shim fixes `num_batch` at 8192; nomic still fails at 10,000 chars even with `num_batch` 4096 (its 2,048-token model limit is hard). `nomic-embed-text` remains installed but unused.
- **Generator / embedder were not otherwise tuned.** Chunk size/overlap (10000/1000), `k` (4), prompt, chain type ("stuff") and temperature come from production code.
- Downloads performed with approval: five arXiv PDFs (≈15 MB, kept out of git), `facebook/bart-large-cnn` (≈1.6 GB), `nomic-embed-text` (274 MB, later rejected), `bge-m3` (1.2 GB). `qwen3.5:4b` (3.4 GB) was already installed.
- Not done: Poppler was not installed (OCR remains unavailable); none of the five papers is scanned, so OCR is not exercised by this corpus.
- Hardware actually used: Ollama (RTX 2050 4 GB + CPU offload as Ollama decides) for RAG; CPU only for BART (torch CPU build).
