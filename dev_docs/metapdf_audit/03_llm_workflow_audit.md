# MetaPDF — LLM Workflow Efficiency Audit (analysis only)

Audited 2026-10-04 on `main` @ `6418b77` (includes the OCR commit `65420cc`). No code was modified, nothing was executed.
Builds on `01_architecture.md`, `02_technology_audit.md`, `KNOWLEDGE_BASE.md`.

Tags: **FACT** = verified in source; **GRAPH** = Graphify; **ESTIMATE** = computed from code constants + stated assumptions (not measured);
**INFERENCE** = reasoned, untested; **KNOWLEDGE** = my background knowledge of upstream libs/services (not verified online).

**Objective:** minimize unnecessary tokens/compute while keeping acceptable quality and latency. Several proposals below *add* tokens on purpose where quality needs it.

## 0. Method, limits, and global assumptions
- GRAPH: refreshed graph after syncing with `main` (182 nodes/257 edges). `graphify query --context call` + `explain` located the LLM-relevant functions: chat → `index()` → {`get_pdf_text`, `get_text_chunks`, `get_vector_store`, `load_vector_store`, `get_conversational_chain`}; summary → `generate_smart_summary()` → {`load_model`, `preprocess_text`}; `extract_pages()` → `hybrid_extract_pages()` → `extract_text_from_image()` → `_get_ocr_reader()` (new OCR path). Graph now also contains `dev_docs` heading nodes (noise).
- FACT: source re-read only where not already documented: `App/ocr_processor.py` (threshold + page loop), `stream_app.py` diff, `chat.html` JS (L96-220). `chat_app.py` / `stream_app.py` summarization code were already read in Phase 1.
- **Nothing was measured.** No token counters exist in the code (FACT: no `usage_metadata`, no logging of tokens). Every number is an ESTIMATE.
- Global assumptions: **4 chars ≈ 1 token** (English prose); **1 page ≈ 500 words ≈ 3,000 chars ≈ 750 tokens**; chat retrieval **k = 4** (library default for `similarity_search`, not set in code — KNOWLEDGE, unverified); API input:output price ratio ≈ 1:4 (typical for Gemini Flash-class models — KNOWLEDGE; the configured model ID is also likely retired, see 02 audit §5.4). Dollar figures are deliberately omitted; relative shares only.

## 1. Inventory of LLM-powered workflows (FACT)
| # | Workflow | Model | Where | API or local | LLM calls |
|---|---|---|---|---|---|
| A | Embedding at upload | Google `models/embedding-001` | `get_vector_store` L57 | API | batched (≈1 request per ≤100 chunks — KNOWLEDGE) |
| B | Question embedding | same | inside `FAISS.similarity_search` (L159) | API | 1 per question |
| C | Answer generation (RAG, "stuff") | `gemini-1.5-flash-8b-001`, temp 0.3, no max tokens | `get_conversational_chain` L83, `index()` L162 | API | 1 per question |
| D | Page/chunk summarization | `facebook/bart-large-cnn`, beam 4 | `generate_smart_summary` L165 | local (CPU/GPU) | 3–5 `generate()` calls per page |
| E | Second-pass summarization | same BART | `generate_smart_summary` | local | 0–1 per page |
| F | OCR (not an LLM, but dominant cost on scans) | EasyOCR, `gpu=True`, dpi 200 | `ocr_processor.py` | local | per sparse page |
No other LLM calls exist. No agents, no tool use, no query rewriting, no reranking, no LLM-as-judge (FACT: grep + graph).

## 2. Workflow 1 — PDF question answering / RAG (`App/chat_app.py`)
### 2.1 Trace
```
User PDF → chat.html handleUpload (auto on file select) → POST /chat/ (pdf_files)
→ [preprocess] none (no cleaning, pages concatenated with no separator, no page numbers kept)
→ [extraction] PyPDF2 extract_text per page; NO OCR in chat path (FACT: chat_app does not import ocr_processor)
→ [chunking] RecursiveCharacterTextSplitter 10000 chars / 1000 overlap (~2,500 tok/chunk)
→ [embedding] Google embedding-001 over all chunks → FAISS → save_local(data/faiss_index) (global, overwritten)
User question → POST /chat/ (user_question)
→ [retrieval] load_vector_store() EVERY question (new embeddings client + FAISS.load_local) → similarity_search(q) (embeds q; top-k, no score, no filter, no rerank)
→ [context construction] chain_type="stuff": all k chunks joined into {context}
→ [prompt] fixed template (~140 words ≈ 170 tok) + context + question; NO chat history
→ [LLM] 1 Gemini call, no max_output_tokens
→ [post-processing] output_text → appended to session['chat_history'] (display only) → JSON
→ [UI] JS typewriter reveal at 30 ms/char
```
### 2.2 Per-question budget (ESTIMATE; assumptions in §0)
| Doc size | chars | chunks (step 9,000) | Context sent (k=4) | Share of doc sent | Input tokens/question | Embedding tokens at upload |
|---|---|---|---|---|---|---|
| 10 pages | 30k | 4 | all 4 (33k chars) | 100% | ≈ 8.4k | ≈ 8.3k |
| 50 pages | 150k | 17 | 4 (40k chars) | ≈ 24% | ≈ 10.2k | ≈ 41k |
| 200 pages | 600k | 67 | 4 (40k chars) | ≈ 6% | ≈ 10.2k | ≈ 166k |
Input ≈ context + ~170 (template) + ~20 (question).
- **Output:** unbounded; the prompt says "maximum detail … leave no aspect … unexplored" and, when context lacks the answer, to *additionally* "offer a DETAILED ANSWER based on relevant knowledge" (FACT L84-100). ESTIMATE 600–1,200 output tokens/answer (assumption; no measurement).
- **Cost shape (ESTIMATE):** with a 1:4 price ratio, 10k input ≈ 10k units vs 900 output ≈ 3.6k units → **input ≈ 70–75% of per-question spend**. Context size, not prompt wording, dominates (the 170-token template is ≈ 1.7% of input).
- **Calls per question:** 2 API calls (1 embedding + 1 generation). Upload: 0 LLM calls. No duplicate LLM calls (FACT).

### 2.3 Waste & bottlenecks found
1. **Retrieval is a no-op for small docs** (≤ 4 chunks ≈ 36k chars ≈ 12 pages): the entire document is sent with every question (ESTIMATE table row 1).
2. **Constant ~10k-token context regardless of question**; for large docs only ~6–24% of the corpus but each chunk is 10,000 chars while an answer typically lives in a paragraph or two (assumption: answer-bearing text ≈ 500–1,500 chars). Signal density of the sent context ≈ 5–15% under that assumption — most tokens are "context-window waste" even though the model's window (~1M, KNOWLEDGE) is not the limit; the cost is.
3. **Adjacent/overlapping chunks:** 1,000-char overlap (10%) means if neighbouring chunks are both retrieved the overlap text is sent twice (≤ ~2.5% of context; minor).
4. **No score threshold / early exit:** an off-topic question ("hi", unrelated topic) still sends 10k tokens and triggers the "use general knowledge" branch.
5. **No conversation context in the LLM call** (FACT: chain inputs are only `input_documents` and `question`). Follow-ups ("explain that more", "what about the second one?") embed poorly and the model has no antecedent → quality loss that costs users extra turns (each = another ~10k-token call). History is stored for display only.
6. **Session-cookie history risk (INFERENCE, untested):** `session['chat_history']` stores full answers in Flask's default client-side cookie; cookies > ~4 KB are dropped by browsers. With 1–4 KB answers, the cookie plausibly overflows after a handful of exchanges, losing `vector_store_created` → "Please upload a PDF first" even though the index exists. Interacts with any plan to send history to the LLM.
7. **Repeated work per question (latency):** `load_vector_store()` + new `GoogleGenerativeAIEmbeddings` + new `ChatGoogleGenerativeAI` + `load_qa_chain` rebuilt on *every* question (FACT L151, L162). No tokens, but avoidable disk/object overhead.
8. **Duplicate processing:** re-uploading the same PDF re-embeds everything (no content hash); a different user's upload overwrites the shared index (FACT, see 01 §8) so work is lost.
9. **Scanned PDFs → empty text** in chat (no OCR): `get_text_chunks("")` returns `[]` → `get_vector_store` returns `None` → user sees "Invalid file format" (misleading). Zero tokens spent but a quality/UX gap now that OCR exists elsewhere.
10. **No page metadata:** pages are concatenated; chunks carry no page number/source, so no citations, no page-scoped filtering, no multi-doc isolation.
11. **Perceived latency from the UI:** the answer is revealed at 30 ms/char (`chat.html` L102/213). A 3,600-char (~900-token) answer takes ≈ **108 s** to display after the API has finished (ESTIMATE from FACT constants). Verbose prompt → long output → long reveal.
12. **Model:** `gemini-1.5-flash-8b` is already the cheapest tier (KNOWLEDGE) — model downsizing is not an available lever; model *validity* is (02 audit §5.4).

## 3. Workflow 2 — PDF summarization (`stream_app.py`, local BART)
### 3.1 Trace
```
User PDF → st.file_uploader → extract_pages() [runs on EVERY Streamlit rerun, uncached]
→ [extraction] hybrid_extract_pages: PyPDF2 per page; page whose whitespace-collapsed text is ≤ 50 chars → "sparse" (FACT L270)
→ [OCR] if any sparse page: convert_from_bytes(content, dpi=200) renders ALL pages, EasyOCR on sparse ones only (FACT L282-294)
→ [cleaning] whitespace collapse
→ user selects pages + quality (Fast 100/30, Balanced 150/50, High 200/75) → click "Generate"
→ per page: skip if ≤20 chars → generate_smart_summary(page_text)
   → preprocess_text: strip "n of m" + URLs, split sentences, group into <1000-char chunks
   → per chunk (skip <15 words): BART summarizer, num_beams=4, length_penalty=1.5, max/min as below
   → join chunk summaries; if >1 chunk and joined words > max_length → SECOND PASS BART over the joined text
→ typewriter render (0.01 s/char, one st.markdown per character) + per-page download button
→ "combined summary" = " ".join(page summaries) (no model call)
```
### 3.2 Length policy (FACT, L165-194 logic) and its effect
`word_count` is computed on the **whole page** text, but `max_length/min_length` are then applied to **each ~1000-char chunk**:
- page > 500 words: `max_length = min(200, 0.3·wc)` → 200; `min_length = max(50, 0.6·max)` → **120 tokens forced minimum per chunk**.
- 100–500 words: slider values (e.g. Balanced 150/50).
- < 100 words: `max_length = min(150, wc)`, `min_length = min(50, max−10)`.
A ~1000-char chunk ≈ 250 tokens; forcing ≥ 120 output tokens means chunk summaries retain **≥ ~50% of the input** (ESTIMATE) — closer to paraphrase than summary. For a 500-word page (3–4 chunks) the joined first-pass summary is ≈ 360–800 tokens, which exceeds `max_length` (200 words limit compared in *words*), so the **second pass fires and compresses it again** (ESTIMATE). The first-pass intermediate output is then discarded: wasted decoder compute. The second pass call omits `num_beams`/`length_penalty` (so pipeline/model-config defaults apply — KNOWLEDGE for BART-large-cnn config) and its input may approach/exceed BART's ~1,024-token limit (KNOWLEDGE); any exception is swallowed and the long concatenation is shown instead (FACT: bare `except: pass`).

### 3.3 Per-page budget (ESTIMATE; 500-word page, >500-word branch)
| Stage | Calls | Encoder tokens in | Decoder tokens out | Notes |
|---|---|---|---|---|
| Chunk summaries | 3–4 | ≈ 3.5 × 250 ≈ 875 | ≈ 3.5 × (120–200) ≈ 420–700 | beam 4 ⇒ ~4× decoder compute |
| Second pass | 0–1 (likely 1) | ≈ 400–800 | ≈ 120–200 | single beam setting differs |
| **Page total** | **≈ 4–5** | **≈ 1.3–1.7k** | **≈ 540–900** | final shown text ≈ 120–200 tokens → ≈ 60–75% of generated tokens are intermediate |
Document of 100 text pages: **≈ 400–500 BART `generate()` calls** (ESTIMATE; wall-clock not measured — if each call took 1–3 s the run is on the order of 7–25 min; assumption only).
API tokens: **0** (all local). "Cost" here is GPU/CPU time and, if on GPU, VRAM (fp16 `.half()`).

### 3.4 Waste & bottlenecks found
1. **No caching of extraction or summaries across Streamlit reruns (FACT: `extract_pages` called at L251 inside `if uploaded_file:` with no `st.cache_data`; no `session_state` anywhere).** Every widget interaction (page-mode radio, page input, quality slider, checkboxes) reruns the script ⇒ re-extraction, and with sparse pages, **full re-OCR (all pages rendered at 200 dpi, then OCR)** each time.
2. **Results live inside `if st.button(...)` (L290).** Streamlit's `st.button` is True only in the run triggered by the click (KNOWLEDGE; INFERENCE for this app, untested): clicking "Show combined summary" or a download button reruns the script with the button False, so the generated summaries vanish and BART must run again to see them. The combined-summary checkbox is inside that block, so it may never display anything. Impact: possible repeated full-document summarization — the largest compute duplicate — and a functional bug. **Needs a manual test.**
3. **Per-chunk length policy driven by page word count** (§3.2): inflates intermediate output and triggers the second pass.
4. **OCR renders every page** even when only a few are sparse: `convert_from_bytes(content, dpi=200)` has no `first_page/last_page/page selection` (FACT L282-288). For a 100-page file with 2 scanned pages: 100 renders vs 2 needed (arithmetic) ⇒ ~98% of rendering work unnecessary.
5. **OCR reader created lazily per process** (`_get_ocr_reader`, module global — FACT L16-22), so model load is once per Streamlit process, but `gpu=True` is hardcoded.
6. **"Combined summary" is concatenation, not a summary:** 100 pages × ≈ 150–200 tokens ≈ **15–20k tokens of "summary"** (ESTIMATE). No document-level reduce stage exists.
7. **Per-page isolation:** each page is summarized without neighbours; headers/footers/boilerplate repeated on every page are summarized every time (only `\d+ of \d+` and URLs are stripped).
8. **UI latency:** typewriter = `time.sleep(0.01)` + one `st.markdown` websocket update **per character**; a 700-char page summary ≈ 7 s of pure animation; 100 pages ≈ **≈ 12 min**, and the combined summary (≈ 70k chars) is typed again ≈ **≈ 12 min** (ESTIMATE from FACT constants), all synchronous in the script thread.
9. **Overlap with API path:** none — summarizer never calls Gemini; privacy-wise it keeps document text local (FACT).

## 4. Cross-cutting findings
- **Two disjoint pipelines** share nothing: extraction code (two PyPDF2 call sites + OCR only in one), chunking (10,000-char char-splitter vs 1,000-char regex grouping), models, UIs, caches. Any optimization (page-aware extraction, caching by content hash) must be done twice unless a shared module is introduced.
- **No telemetry:** no token counts, latencies, hit rates, or cache stats are logged anywhere. Without these, all estimates here stay estimates.
- **Local vs API split today:** summarization local (no data egress, compute-bound), chat API (egress of ≈ 10k tokens of document per question + embeddings of the whole document). Neither is "wrong"; the egress and the cost both scale with context size.
- **Changes since 01/02 audits (OCR commit):** `requirements.txt` gained `easyocr`, `pdf2image`, `Pillow`, `numpy`; `pdf2image` needs Poppler installed on the OS and EasyOCR pulls PyTorch (KNOWLEDGE); `streamlit`/`torch` remain undeclared. `extract_pages` now sets `sys.path` inside the function and re-reads the whole file into memory.

## 5. Optimization opportunities
Each item: **Current → Proposed → Token/compute reduction (assumptions) → Quality → Latency → Complexity.** All reductions are ESTIMATES; validate with an evaluation set (§6, step 0). Not implemented.

### O1. Smaller chunks + right-sized k (chat)
- **Current:** 10,000/1,000-char chunks, k=4 ⇒ ≈ 10k input tokens/question for docs > 12 pages; whole doc for small docs.
- **Proposed:** ≈ 1,000–1,500-char chunks (≈ 250–375 tok), ~10–15% overlap, k≈4–6, optional neighbouring-chunk expansion for top hit only.
- **Reduction:** context ≈ 1.0k–2.2k tokens vs 10k ⇒ **≈ 75–90% fewer input tokens/question**, *assuming* answer-bearing text is localized to ≲ 1–2 paragraphs (typical factual Q&A; false for "summarize the whole doc" or multi-section synthesis). Embedding tokens at upload unchanged (+ overlap), but embedding *requests* rise ~7× in count (still batched).
- **Quality:** usually better precision (less distraction); risk of missing multi-paragraph answers ⇒ mitigate with higher k/neighbour expansion; must be tested on real questions.
- **Latency:** lower generation latency (smaller prompt); retrieval unchanged.
- **Complexity:** low (constants) but requires re-indexing; needs eval set.

### O2. Score threshold, adaptive k, and early exit
- **Current:** fixed top-k regardless of relevance; always calls the LLM.
- **Proposed:** `similarity_search_with_score`, drop chunks below a relative score cutoff, cap by a **token budget** (e.g. ≤ 2–3k tokens); if the best score is very poor, answer "not found in the document" **without an LLM call**; for documents whose total size is under the budget, send the whole document (no retrieval error possible).
- **Reduction:** off-topic questions: 100% of that call; on-topic: further trims from O1 (maybe 0–40% more, depends on score distribution — unknown without data).
- **Quality:** fewer irrelevant chunks, honest "not found"; threshold needs calibration per embedding model (scores aren't portable).
- **Latency:** improves. **Complexity:** low–medium (calibration).

### O3. Bounded conversation context + standalone-question rewriting
- **Current:** no history in the LLM call; follow-ups retrieve and answer without antecedent.
- **Proposed:** keep last 2–3 turns in a compact form; rewrite follow-ups into a standalone query (skip when no history or question is self-contained) used for *retrieval*; optionally pass a short summary of recent turns (~200–400 tokens) to the generator.
- **Reduction:** **net tokens increase slightly** (+ ≈ 300 in / ≈ 30 out per rewritten turn, + 200–400 context) — justified by quality; offset by O1. Saves user re-asks (each re-ask ≈ a full call).
- **Quality:** clearly better on follow-ups. **Latency:** + one small call (~0.3–1 s) only on follow-ups. **Complexity:** medium. Pair with moving history out of the cookie (server-side store) — see §2.3 item 6.

### O4. Output control and grounded prompt
- **Current:** "maximum detail … leave no aspect unexplored" + fallback to general knowledge; no `max_output_tokens`; 30 ms/char reveal.
- **Proposed:** concise-by-default instruction (expand on request / "Detailed" toggle), explicit grounding rule (answer only from context; if absent, say so — optionally allow flagged outside knowledge), request page/chunk citations, set `max_output_tokens` (e.g. ~400–600).
- **Reduction:** output ≈ 600–1,200 → ≈ 200–500 tokens (**≈ 50–70%**, assuming typical answers don't need more; users wanting depth use the toggle). Output is ≈ 25–30% of per-question spend under the 1:4 ratio ⇒ ≈ 12–20% of total spend on its own (ESTIMATE). Shortening the template text itself saves ≈ 1% — not worth prioritizing.
- **Quality:** fewer hallucinated "general knowledge" tails; users who liked long answers need the toggle. **Latency:** large perceived gain (shorter generation + shorter 30 ms/char reveal). **Complexity:** low.

### O5. Content-hash caching and per-document indices
- **Current:** every upload re-embeds; one global index overwritten by any upload; index and clients reloaded per question.
- **Proposed:** key index by SHA-256 of the PDF bytes; skip embedding when present; per-session/per-document index path; cache loaded FAISS + clients in memory.
- **Reduction:** 100% of embedding tokens/requests on re-uploads (hit-rate unknown — likely low for a single-user demo, higher in shared use); removes per-question disk load. Also fixes cross-user overwrite (quality/correctness).
- **Quality:** neutral/positive. **Latency:** saves upload time on hits, saves ms per question. **Complexity:** medium.

### O6. Page-aware extraction + chunk metadata
- **Current:** pages concatenated; no metadata.
- **Proposed:** extract per page; carry `{source, page}` as chunk metadata; enable citations, "on page N" filters, multi-document filtering; strip repeated headers/footers (lines recurring on > ~50% of pages).
- **Reduction:** small direct token savings (assumption: boilerplate ≈ 1–5% of text, document-dependent — unmeasured); main value is retrieval precision and verifiability.
- **Quality:** better (citations, scoping). **Latency:** neutral. **Complexity:** medium (touches extraction, splitter, response format). Could share one extraction module with the summarizer.

### O7. MMR or reranking with over-fetch
- **Current:** top-k by raw similarity.
- **Proposed:** fetch ~15–20 candidates cheaply, then MMR (diversity) or a small local cross-encoder to keep the best 3–5; dedupe overlapping adjacent chunks.
- **Reduction:** allows a wider recall net without wider LLM context; context stays ≈ O1's budget. Overlap dedupe saves ≲ 2.5%.
- **Quality:** typically improves recall@small-context; local reranker adds a model dependency. **Latency:** + ≈ tens–hundreds of ms locally (assumption). **Complexity:** medium. Do after O1/O2 and only if the eval shows recall misses.

### O8. Context compression (extractive)
- **Current:** whole chunks are sent.
- **Proposed:** after retrieval, keep only the sentences most similar to the question (plus neighbours), or use a prompt-compression model.
- **Reduction:** substantial when chunks are large (could approximate O1's gain without re-indexing: e.g. 10k → 2–3k); **marginal after O1** (small chunks already tight).
- **Quality:** risk of dropping needed sentences. **Latency:** + small. **Complexity:** medium. **Recommendation:** treat as an alternative to O1, not an addition.

### O9. Fix the summarizer length policy and drop the redundant second pass
- **Current:** page-level `word_count` sets per-chunk min/max (min up to 120 tokens per ~250-token chunk) ⇒ weak compression, then a second pass re-compresses.
- **Proposed:** derive lengths **per chunk** from the chunk's own size with a target compression (e.g. 25–40% of input tokens, bounded by the model's limits); if more than one chunk, either skip the page-level re-summarization or make it a deliberate reduce step with an explicit budget and consistent beam settings.
- **Reduction (ESTIMATE):** per 500-word page generated tokens ≈ 540–900 → ≈ 250–350 (3.5 chunks × ~70–80 tokens, no second pass) ⇒ **≈ 50–65% fewer decoder tokens and ≈ 1 fewer generate call**; assumes 25–40% target compression is acceptable for the user's "Balanced" setting.
- **Quality:** tighter, less redundant; very short summaries risk losing detail — keep the slider mapped to compression targets. **Latency:** ≈ 30–50% faster per page (generate calls ≈ 4–5 → 3–4, shorter outputs; not measured). **Complexity:** low–medium.

### O10. Hierarchical (map-reduce) document summary
- **Current:** "Complete Document Summary" = concatenated page summaries (≈ 15–20k tokens for 100 pages).
- **Proposed:** map: page/section summaries (as O9); reduce: group ~8–10 page summaries → section summary → final summary of ≈ 300–600 tokens. Section boundaries by headings/page ranges rather than fixed pages when detectable.
- **Reduction:** deliverable shrinks ≈ 95%+ (15–20k → ≤ 600 tokens); compute adds ≈ N/10 + 1 calls (≈ 11 for 100 pages) on small inputs.
- **Quality:** converts a pile of snippets into an actual overview. The reduce stage can run on BART (≈ 1,024-token input limit ⇒ group size must fit) **or** a single call to an API model over ≈ 15–20k tokens once (privacy trade-off; cost of one call ≪ chat's per-question 10k tokens × many questions). **Latency:** + one stage. **Complexity:** medium.

### O11. Persist extraction and summaries across Streamlit reruns
- **Current:** nothing cached; `extract_pages` and (possibly) all BART runs repeat on every interaction (§3.4 items 1–2).
- **Proposed:** `st.cache_data` for extraction keyed by file bytes hash; cache page summaries in `st.session_state` or `st.cache_data` keyed by `(file hash, page, settings)`; render results from state independent of the button's one-run truthiness; unblock the combined-summary checkbox/download.
- **Reduction:** **up to 100% of repeated extraction/OCR/BART work after the first run**; frequency = number of post-generation interactions (unknown, likely several per session). This is the highest-confidence compute saver and also fixes the suspected functional bug.
- **Quality:** neutral/positive (results no longer disappear). **Latency:** large improvement on every interaction after the first. **Complexity:** low–medium.

### O12. OCR only the pages that need it
- **Current:** if any page is sparse, **all** pages are rasterized at 200 dpi; OCR runs only on sparse ones.
- **Proposed:** rasterize only sparse page indices (pdf2image supports first/last page parameters — KNOWLEDGE), cache OCR text by `(file hash, page)`; consider lower dpi for large-print pages.
- **Reduction:** rendering work ∝ sparse/total pages (e.g. 2/100 ⇒ ≈ 98% fewer renders); OCR itself unchanged. Memory spike also drops (all pages in memory at 200 dpi).
- **Quality:** neutral. **Latency:** large for mostly-text PDFs with few scans. **Complexity:** low.

### O13. Cut UI animation latency
- **Current:** Streamlit typewriter 0.01 s/char + a render per char; chat reveal 30 ms/char.
- **Proposed:** render once (or in coarse steps), keep animation optional/client-side and capped in duration.
- **Reduction:** 0 tokens; removes ≈ 7 s/page and ≈ 12 min per 100-page run twice (ESTIMATE from constants), and up to ≈ 100 s per long chat answer.
- **Quality:** neutral. **Latency:** large. **Complexity:** very low.

### O14. Local embeddings (and local models for cheap stages)
- **Current:** every chunk and every question embedded via Google API.
- **Proposed:** a small local sentence-embedding model for indexing/search; optionally a small local model for query rewriting/classification (O3, O2 routing), keeping the main generation on the API (or evaluate a local generator separately).
- **Reduction:** eliminates 100% of embedding API tokens/requests (≈ 8k–166k tokens/upload per the table, + ~20 tokens/question) and removes an egress path; generation tokens unchanged.
- **Quality:** retrieval quality depends on the chosen model — must be benchmarked on the user's documents; all existing indices must be rebuilt (stored index carries no model metadata — INFERENCE). **Latency:** local CPU/GPU cost at index time; saves network round-trips. **Complexity:** medium; adds a dependency alongside torch already present.

### O15. Model routing / selection
- **Current:** one model for every question.
- **Proposed:** route trivial lookups to the cheapest model, harder synthesis questions to a stronger one; or answer "not found" locally (O2).
- **Reduction:** minimal here — the configured model is already the smallest tier (KNOWLEDGE) and volume is small; the real action item is replacing the likely-retired model ID.
- **Quality/Latency:** depends on classifier accuracy. **Complexity:** medium. **Low priority.**

### O16. Response caching and semantic dedup
- **Current:** none.
- **Proposed:** cache `(document hash, normalized question) → answer`; semantic dedup of near-duplicate chunks at index time.
- **Reduction:** only on repeats; expected hit-rate low in interactive use (INFERENCE); dedup gains small after O7. **Low priority.**

## 6. Prioritized opportunities (highest impact first)
0. **Instrument first (prerequisite):** log per-request input/output tokens (Gemini usage metadata), embedding counts, retrieval scores, BART call counts/latency; build a small golden set of real documents + questions. Without this, O1/O2/O9 thresholds are guesses. Complexity: low.
1. **O1 + O2 — smaller chunks, token-budgeted retrieval, early exit (chat).** Biggest API-cost lever: ≈ 10k → ≈ 1–2.5k input tokens/question (ESTIMATE), and fixes "whole document sent every time" for small docs. Quality-sensitive ⇒ evaluate.
2. **O11 + O12 — persist extraction/summaries; OCR only sparse pages (Streamlit).** Highest-confidence compute saver; likely also fixes a user-visible bug (vanishing results / combined summary). Low risk.
3. **O9 — fix summarizer length policy, remove redundant second pass.** ≈ 50–65% fewer decoder tokens and fewer calls per page (ESTIMATE); improves summary tightness.
4. **O4 — concise grounded prompt + `max_output_tokens`.** ≈ 12–20% of per-question spend and the largest perceived-latency gain on the chat side; also reduces ungrounded answers. Easy.
5. **O13 — remove per-character animation delays.** Zero-risk latency win (minutes on long documents).
6. **O10 — hierarchical document summary.** Biggest quality jump for the summarization feature; modest extra compute.
7. **O3 (+ server-side history) — standalone-question rewriting and bounded history.** Quality fix with small token cost; also resolves the likely cookie-size failure.
8. **O6, O7 — page metadata/citations, MMR/rerank.** Quality and verifiability; do after measuring recall.
9. **O5, O14 — content-hash/per-document indices; local embeddings.** Correctness (multi-user isolation) and egress/cost; heavier changes, re-index required.
10. **O8, O15, O16** — situational/low value once the above are in place.

## 7. Open questions / what would change these estimates
- Real token counts and latency (no measurements exist). Real answer length distribution; real document sizes in use.
- Installed `langchain-community` default `k`, and whether `similarity_search` default is 4 in the user's version.
- Whether Streamlit's rerun semantics actually discard results after the checkbox/download click in the pinned version (manual test).
- BART input truncation behavior for the second pass on the installed `transformers` (5.x installed on this machine — pipeline behaviour unverified).
- Actual hardware (GPU/CPU) for BART and EasyOCR; actual Gemini model availability for the configured IDs.
- Whether users ask mostly factual lookups (favors O1) or broad "explain this document" questions (favors summary-first / hierarchical approaches over small-chunk RAG).
- Contents of the committed `instance/faiss_index/index.pkl` (5,952 bytes): a raw-byte scan (not an unpickle) shows HTML-tutorial text, consistent with a stale test index (INFERENCE).
