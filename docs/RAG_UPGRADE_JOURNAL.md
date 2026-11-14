# MetaPDF RAG Upgrade — A Student's Guide to What We Did and Why

> This is a living journal. It explains the upgrade the way a senior engineer would explain it to a junior:
> what we found, what we decided, what we built, what we measured, and what we deliberately did **not** do.
> Read it top to bottom once; afterwards use the headings as a reference.

---

## 0. The goal in one paragraph

MetaPDF already let you upload a PDF and "chat" with it. The goal of this upgrade is to turn that feature into a
**measurable, modern Retrieval-Augmented Generation (RAG) system** — one where every design choice (chunk size,
search method, reranker, prompt) is backed by a number we measured, and where we know what each question costs in
tokens and how often the model makes things up (hallucinates). That is what makes a RAG project credible in an
interview: not "I used LangChain", but "hybrid search raised evidence recall from X to Y, and this is how I measured it".

---

## 1. Quick vocabulary (read this first)

| Term | Plain-English meaning |
|---|---|
| **RAG** | Instead of asking the LLM from memory, we first *retrieve* the relevant pieces of the document and paste them into the prompt, so the model answers *from the document*. |
| **Chunk** | A small piece of the document (e.g. ~300 tokens). We search over chunks, not whole documents. |
| **Embedding** | A list of numbers (a vector) that represents the meaning of a text. Similar meanings → nearby vectors. |
| **Dense retrieval** | Find chunks whose embedding is closest to the question's embedding (semantic search). |
| **BM25** | Classic keyword search (like a search engine before neural nets). Great for exact names and numbers. |
| **Hybrid search** | Run dense + BM25, then merge the two ranked lists. |
| **RRF (Reciprocal Rank Fusion)** | A simple merging rule: each chunk gets `1/(60 + rank)` from each list; sum them. Robust, no tuning of score scales. |
| **Reranker (cross-encoder)** | A slower but more accurate model that reads (question, chunk) *together* and scores relevance. We use it on the top ~30 candidates only. |
| **Token** | The unit LLMs read and bill by (~¾ of an English word). Cost = input tokens × price + output tokens × price. |
| **Hallucination** | The model states something that the document does not support. |
| **Faithfulness / groundedness** | The share of the answer's claims that are supported by the retrieved text. |
| **Recall@k / Hit@k / MRR** | Retrieval metrics. *Hit@k*: did the right evidence appear in the top k chunks at all? *Recall@k*: what fraction of all needed evidence appeared? *MRR*: how high up was the first correct chunk (1/rank)? |
| **Ablation** | Turn features on one at a time and measure each one's effect. |

---

## 2. What we found (the starting point)

Before changing anything, earlier audit work (see `dev_docs/metapdf_audit/`) and fresh checks in this session showed:

1. **The chat feature was broken.** The code used `models/gemini-1.5-flash-8b-001` and `models/embedding-001`.
   Both now return **404 NOT FOUND** from Google — these models were retired. So uploading a PDF failed silently.
2. **The code used removed LangChain APIs.** `from langchain.chains.question_answering import load_qa_chain` and
   `langchain.text_splitter` no longer exist in LangChain 1.x. The module could not even be imported.
3. **The RAG design was "naive RAG":**
   - chunks of **10,000 characters** (≈2,500 tokens each) — far too big; the retriever can't be precise;
   - **dense search only**, default k = 4 → about **10,000 input tokens per question** sent to the LLM;
   - no citations, no page numbers, no conversation memory;
   - the prompt told the model to answer "with maximum detail" and to **fall back on general knowledge** if the document
     lacked the answer — that instruction literally invites hallucination;
   - **one global FAISS index** for every user (uploading a new PDF overwrote everyone's index) saved with Python
     `pickle` (`allow_dangerous_deserialization=True`).
4. **No measurement:** no token counts, no cost, no latency, no quality numbers.
5. **Assets we could reuse:** an evaluation set already existed in `eval/`: **5 well-known AI papers**
   (Attention Is All You Need, RAG (Lewis et al.), Constitutional AI, GPT-3, PaLM — 15 to 87 pages) and
   **40 questions** with gold answers, gold page numbers and **verbatim evidence quotes**, including 5 unanswerable
   questions (to test whether the system admits "not in the document") and 5 follow-up questions.

## 3. The constraints we designed around

- **Gemini only** for answer generation (owner's decision).
- **Free-tier rate limits** (possibly as low as ~20 requests/day per model). So the design rule became:
  *only the final answer generation uses Gemini; everything else runs locally.*
- A laptop GPU: **NVIDIA RTX 2050, 4 GB VRAM** — enough for small embedding/reranker models.
- Keep Flask + Streamlit UI; keep the Office converters as-is (out of scope).

## 4. Key decisions (and why)

| Decision | Why |
|---|---|
| **Local embeddings** (`BAAI/bge` family via `sentence-transformers`) instead of Gemini embeddings | 0 API calls for indexing (a 87-page paper would otherwise cost hundreds of embedding requests), no quota, documents never leave the machine for indexing, and we can re-run experiments for free. |
| **Local cross-encoder reranker** (`BAAI/bge-reranker`) | Industry-standard "retrieve many, rerank, keep few" pattern; free to run. |
| **Local NLI model for hallucination scoring** (`cross-encoder/nli-deberta-v3`) instead of an LLM judge | An LLM judge would burn our tiny Gemini quota and the model would partly grade itself. NLI (Natural Language Inference) models are trained exactly to answer "does text A support sentence B?". |
| **Plain FAISS + NumPy files instead of pickle** | Removes the unsafe deserialization; index stored per document (keyed by SHA-256 of the file), so users don't overwrite each other and re-uploading the same file costs nothing. |
| **google-genai SDK directly** for generation (no LangChain chain) | We need exact token usage (`usage_metadata`) for cost tracking, and the old chain API is gone anyway. Fewer layers = easier to explain and debug. |
| **pypdf instead of PyPDF2** | PyPDF2 is deprecated; pypdf is its maintained successor. We checked: with whitespace-insensitive matching, 71/73 gold quotes are found in pypdf's text (the 2 misses were garbled glyphs in PyPDF2's own output). |
| **Disk cache for every Gemini call** | Re-running the evaluation costs 0 requests. |
| **Measure retrieval offline first** | Retrieval quality (did we fetch the right evidence?) needs no LLM at all, so we can try dozens of configurations for free and only spend Gemini calls on the final comparison. |

---

## 4b. What we deliberately did NOT do (and why)

Saying "no" is part of engineering. Each of these was considered and postponed on purpose:

| Not done | Why not (yet) |
|---|---|
| LLM-written contextual chunk summaries (full "contextual retrieval") | One Gemini call per chunk (hundreds per PDF) on a free-tier quota. The cheap title/page header already gave +14 hit points. |
| LLM query rewriting for follow-ups | It would double API calls per question. History-aware retrieval (previous + current question) fixed the measured follow-up miss at zero cost. |
| LLM-as-a-judge (RAGAS / DeepEval with Gemini) | Burns quota, and the generator's family would grade itself. We used a local NLI checker plus deterministic key-fact checks. RAGAS/DeepEval could be plugged in later with a different judge model. |
| Corrective-RAG / LangGraph agent loop | Adds 1–3 extra LLM calls per question. Worth doing only once data shows failures that a retry would fix. Listed as future work. |
| Vector database (Qdrant, pgvector) | One user, one document at a time, a few hundred chunks. FAISS in memory takes milliseconds. A DB is justified only for multi-user, multi-document scale. |
| LangChain chains | The old ones were removed in LangChain 1.x. Our pipeline is about 400 lines of plain Python that is easy to read and debug, and gives exact token counts. LangChain is kept only for the legacy-baseline splitter. |
| Docling layout parsing | Better on tables and multi-column layouts, but a heavy install. pypdf found 71/73 gold quotes. Tables are the known weak spot (see limitations). |
| Re-architecting the summarizer and converters | Out of scope by the owner's choice. We only moved them off the deprecated PyPDF2. |

## 5. Progress log

*(Updated as work happens — newest entries at the bottom.)*

### Step 1 — Inspection and environment
- Confirmed the 404s on both old Gemini models; confirmed LangChain 1.x import failures.
- Installed local-model tooling (`sentence-transformers`, `rank_bm25`, `pypdf`) and a CUDA build of PyTorch so the
  GPU can be used.
- Restored the 5 evaluation PDFs (kept out of git for licence reasons; see `eval/corpus/manifest.json` for sources).
- Picked the Gemini model by testing, not guessing: `gemini-2.5-flash-lite` now returns *"no longer available to new
  users"*, `gemini-3.1-flash-lite` was overloaded (503), **`gemini-3.5-flash-lite` works** and uses no hidden
  "thinking" tokens. Official paid-tier price: **$0.30 / 1M input tokens, $2.50 / 1M output tokens** (free tier: $0).
  Lesson: model IDs die — keep them in config, never hard-code them in five places.

### Step 2 — New architecture: `App/rag/`

The old `chat_app.py` did everything inside one 75-line route function. We split it into small modules, each with
one job. This is the single most useful structural change: the web app and the evaluation scripts now call
**the exact same code**, so what we measure is what users get.

```
App/rag/
├── config.py        all tunable numbers (chunk size, k, models, prices) in ONE place, overridable by env vars
├── extract.py       PDF -> list of page texts (pypdf), light cleaning, file hash
├── chunking.py      pages -> chunks that remember their page numbers (+ the legacy chunker for comparison)
├── models.py        lazy loading of local models on GPU (fp16) or CPU
├── index.py         per-document index: FAISS (dense) + BM25 (keywords), saved as JSON/NumPy (no pickle)
├── retrieve.py      dense / BM25 / hybrid-RRF search, then cross-encoder reranking
├── prompts.py       the grounded prompt (and the old prompt, kept only for the before/after test)
├── llm.py           Gemini call: exact token counts, $ cost, disk cache, rate-limit handling
├── faithfulness.py  local NLI hallucination checker
└── pipeline.py      RAGService.ingest() and RAGService.ask() — the public API
```

**How a question flows now:**

```
question ──► (follow-up? add previous question) ──► dense search top-30 ─┐
                                                    BM25 search  top-30 ─┴─► RRF merge ─► reranker ─► top-5 chunks
top-5 chunks + rules ("only use excerpts, cite pages, say 'not in document'") ─► Gemini ─► answer [p. 3]
                                                                     └─► log: tokens, $, latency per stage
```

**Design details worth being able to explain in an interview:**

1. *Chunking by tokens and sentences.* Old: 10,000 characters cut anywhere (mid-sentence, mid-number). New: whole
   sentences packed up to **320 tokens**, counted with the embedding model's own tokenizer (so a chunk always fits
   the embedder's 512-token window), with **48 tokens of overlap** so a fact sitting on a boundary appears in both
   neighbours. Each chunk stores `page_start/page_end` → that's what powers citations like `[pp. 4-5]`.
   Sanity check: all 14 gold quotes of the Attention paper land fully inside some chunk.
2. *Contextual headers.* Before embedding, each chunk gets a prefix like `Attention Is All You Need | p. 8`. This is a
   cheap version of Anthropic's "contextual retrieval": the chunk alone may say "our model achieves 28.4" without
   saying *which* paper/model; the header adds that context. We use a heuristic header (title + page) instead of an
   LLM-written summary per chunk, because that would cost one Gemini call per chunk (hundreds per PDF).
3. *Why hybrid search?* Dense embeddings understand meaning ("how long did training take" ≈ "trained for 3.5 days")
   but are weak on exact tokens like `WMT 2014`, `P100`, `d_k`. BM25 is the opposite. RRF merges both lists by rank
   only, so we never have to make cosine scores and BM25 scores comparable.
4. *Why a reranker?* The embedder encodes question and chunk **separately** (fast, approximate). The cross-encoder
   reads them **together** (slow, precise). So: cheap search for 30 candidates, expensive scoring for only those 30.
5. *History-aware retrieval without an extra LLM call.* A follow-up like "And what did that same model score on
   English-to-French?" contains no searchable subject. Production systems often call the LLM to rewrite it into a
   standalone question — that doubles Gemini usage. We instead search with *previous question + current question*
   (only for short / pronoun-style follow-ups) and pass the last 2 turns to the prompt. Zero extra API calls.
6. *Grounded prompt.* The old prompt said "answer with maximum detail … then offer a DETAILED ANSWER based on relevant
   knowledge". That *asks* for hallucination. The new rules: excerpts only, cite pages, say exactly *"The document
   does not contain this information."* when it's not there, 1–5 sentences, `max_output_tokens = 512`.
7. *Cost accounting.* Token counts come from Gemini's `usage_metadata` (exact, not estimated). Cost = tokens × the
   official price table in `config.py`. Every request is logged to `data/metrics/requests.jsonl`; `/chat/stats`
   aggregates it.
8. *Safety fixes along the way:* per-document index folders (named by file hash + settings hash) instead of one
   global index; no pickle; chat UI renders text with `textContent` (the old `innerHTML` let a malicious PDF inject
   script through the model's answer); upload size limit; Flask debug mode off by default; errors no longer leak
   raw exception text to the browser.

### Step 3 — Retrieval experiment (offline, 0 Gemini calls)

**Question we asked:** for each question, does the retriever bring back the passage that actually contains the
answer? We know the right passage because every question in `eval/questions.jsonl` has a verbatim gold quote.
A quote counts as "retrieved" if it appears inside one of the chunks sent to the LLM (compared ignoring spaces and
punctuation, because different PDF libraries space text differently).

Script: `eval/run_retrieval_ablation.py` → `eval/results/retrieval_ablation.md`. 35 answerable questions, 5 papers,
runs on the GPU in about 3 minutes. Each lettered row adds **one** change to the row above it.

| Configuration | Hit@k | Recall@k | All evidence | MRR | Context tokens sent to LLM |
|---|---|---|---|---|---|
| A. Original design (10k-char chunks, dense, k=4) | 0.714 | 0.648 | 0.571 | 0.488 | 9,454 |
| B. Token chunks (512 tok, sentence-aligned, dense, k=5) | 0.714 | 0.635 | 0.543 | 0.553 | 2,384 |
| C. + contextual headers | 0.829 | 0.764 | 0.686 | 0.587 | 2,401 |
| D. BM25 keyword only (for reference) | 0.886 | 0.754 | 0.629 | 0.639 | 2,418 |
| E. Hybrid dense + BM25 (RRF) | 0.886 | 0.778 | 0.657 | 0.652 | 2,410 |
| F. + cross-encoder reranker | 0.914 | 0.835 | 0.743 | 0.754 | 2,408 |
| **G. + history-aware follow-ups (final)** | **0.943** | **0.864** | **0.771** | **0.780** | **2,409** |

(Final run with the chosen `bge-small-en-v1.5` embedder. An earlier run with bge-base gave the same final row G and
slightly different intermediate rows; the conclusions below hold for both.)

**How to read this (the story you tell in an interview):**

- **A → G: the right evidence reaches the LLM for 94% of questions instead of 71%, while sending 75% fewer
  tokens** (2.4k instead of 9.5k). Better *and* cheaper. That combination is the whole point of good retrieval.
- **B alone gives no gain in hit rate over A, and that's expected.** Huge 10k-character chunks "hit" often because
  each one covers about 4 pages; you're sending a quarter of the paper. Smaller chunks cut tokens by 75% at equal hit
  rate, and they only become a *quality* win once ranking is good. That is why chunking must be evaluated
  *together* with retrieval, not alone.
- **Contextual headers (+11 hit points, B→C)** were a cheap, big win. Research papers repeat terms like "our model",
  and the title/page header gives the embedder the missing context.
- **BM25 alone beat dense alone on this corpus.** Scientific questions are full of exact tokens like "WMT 2014",
  "P100" and "540B". This is the classic argument for hybrid search.
- **Hybrid (E) matched BM25's hit rate and beat it on recall and MRR.** RRF combines the two rankers' strengths.
  Its main value is *recall at depth*: it puts more good candidates in the top 30, and the reranker then picks the
  best of those 30 (F).
- **The reranker gives the biggest MRR jump** (0.65 → 0.75) and +3 hit points, at ~380 ms per question on a laptop
  GPU. Worth it.
- **History-aware retrieval** fixed a follow-up ("And what did that same big model score on English-to-French?")
  and raised the follow-up hit rate from 0.6 to 0.8.

**Sweeps (to choose the settings rather than guess them):**

| Change from final config | Hit@k | Recall@k | MRR | Context tokens |
|---|---|---|---|---|
| chunks 192 tokens | 0.829 | 0.670 | 0.645 | 837 |
| chunks 320 tokens | 0.886 | 0.765 | 0.688 | 1,474 |
| **chunks 512 tokens (chosen)** | **0.943** | **0.864** | **0.780** | **2,409** |
| final k = 3 | 0.857 | 0.735 | 0.762 | 1,451 |
| final k = 8 | 1.000 | 0.935 | 0.788 | 3,865 |
| no BM25 (dense + rerank) | 0.943 | 0.835 | 0.724 | 2,408 |
| embedder bge-base (110M params, 3× larger) | 0.943 | 0.864 | 0.780 | 2,412 |
| embedder all-MiniLM-L6 (22M params) | 0.943 | 0.864 | 0.780 | 2,404 |

- **k is a cost/quality dial.** k=8 finds evidence for every question but sends 60% more tokens than k=5. We kept
  k=5; k=8 is one env-var away (`RAG_FINAL_K=8`) if quality matters more than cost.
- **BM25 still earns its place even with a reranker**: removing it keeps hit@k but lowers recall (0.86 → 0.84) and
  MRR (0.78 → 0.72).
- **The embedder size did not matter once BM25 + reranker were in place**: bge-small (33M), bge-base (110M) and
  MiniLM (22M) score identically. We use the small `bge-small-en-v1.5`, which means faster indexing and less GPU memory.
- A finer sweep (384/448/512 tokens × overlap 48/64/96 × k 4/5/6, kept in `eval/results/_work/sweep2/`) was
  **noisy**: 512/64 beat 512/96, which has no good explanation. **Honest caveat: with 35 questions, one question is
  about 3 percentage points.** Treat differences under ~6 points as noise. The robust conclusions are the big ones:
  reranker ≫ none, hybrid/BM25 > dense-only for this kind of document, and ~2.4k context tokens are enough.
- Known handicap of row A: a 10k-character chunk is ~2,500 tokens, but embedders only read the first 512, so
  the end of each big chunk is effectively invisible to dense search. The original Gemini embedder had a similar
  (2,048-token) limit. This is one more reason huge chunks are a bad idea.

### Step 4 — Building a hallucination checker we can trust

Before trusting any "hallucination rate", we tested the checker on sentences where we *know* the answer:

- First version (one NLI model, `nli-deberta-v3-base`) wrongly flagged a **true** sentence as hallucinated.
  Debugging showed why: the stray space left after removing a citation (`GPUs [p. 7].` → `GPUs .`) dropped the
  entailment probability from 0.97 to 0.17, and "base model" vs "base models" did the same. NLI models are brittle.
- Fixes: clean punctuation after removing citations, and use **two NLI models** (deberta-v3 base + small); a sentence
  counts as supported if *either* finds an excerpt that entails it. Fabricated facts fail both.
- Re-test: **7/7 correct**: 2 true sentences → grounded; wrong layer count, wrong BLEU number, wrong step count,
  invented hardware and an outside-knowledge sentence ("…such as BERT and GPT") → all flagged.
- Then the **first real Gemini answer** exposed two more problems. The answer *"Based on the provided context, the
  encoder of the Transformer is composed of a stack of $N = 6$ identical layers."* is correct, but scored 0.004:
  1. LaTeX (`$N = 6$`) and the filler opener "Based on the provided context," confused the model → we strip math
     markers and such openers before checking (the *claim* is what comes after the comma).
  2. Deeper issue: the excerpt says "The encoder is composed of…" and never says "Transformer". NLI is literal, so
     "the encoder **of the Transformer**" is "not entailed". A human reader knows which paper they are reading, so
     the judge now sees each excerpt prefixed with *From the document "Attention Is All You Need": …*.
- Final checker test: **8/8** (3 true incl. that real answer, 5 fabricated → all correct). We stopped the run,
  fixed it and re-ran; answers were cached, so the fix cost **0 extra API calls**. The eval script also stores the
  retrieved excerpts with every answer, and `--rescore` recomputes hallucination scores offline.

### Step 5 — A production bug found by the evaluation: no timeout

The first full run **hung for several minutes on question 2**, with no output and no error. Cause: the Gemini client
was created without an HTTP timeout, so one stalled connection could block a request forever. In the web app that
would mean a user's spinner turning forever and a Flask worker stuck.
Fix in `llm.py`: a 60 s request timeout, retries with back-off for timeouts, network errors and 5xx "model
overloaded" responses, and a log line for every retry so a slow run is never a silent run.
Lesson: **evaluation runs are also load tests**. Running 80 real requests found a reliability bug that 10 manual
clicks never would.

### Step 6 — Testing the real web app (and two more findings)

We drove the actual Flask UI in a browser: uploaded *Attention Is All You Need* through the page's own upload
flow, then typed a question.

1. **Bug found: the document title was wrong.** The upload message said
   *Indexed "reproduce the tables and figures in this paper solely for use in journalistic…"*. The title guesser
   took the first line of page 1, which on arXiv papers is Google's licence notice. That title is stamped into every
   chunk's contextual header, so a wrong title quietly hurts retrieval. (The eval passed the real titles in, so it
   never noticed. **This is why you also test the real app, not only the eval harness.**)
   Fix: use the PDF's metadata title if it is sensible, else the first *Title-Case* line that isn't licence or
   affiliation boilerplate, joining a wrapped second line ("…Generation for" + "Knowledge-Intensive NLP Tasks").
   Result: **5/5 titles correct** on the eval papers. We bumped the index version so stale indices rebuild.
2. **Memory limit found.** Asking a question while the 80-question evaluation was also running failed with Windows
   error 1455 (*"paging file is too small"*): two processes each holding embedder + reranker (+ NLI models in the
   eval) were too much for a 16 GB laptop. The app handled it correctly. The user saw *"Something went wrong while
   answering. Please try again."* with no stack trace, and the full traceback went to the server log. Not a code bug,
   but a deployment note: **one model-serving process per small machine**, or a shared model server.
3. **Gemini latency is the bottleneck, not our pipeline.** During the run Gemini 3.5 Flash-Lite answered in 3–55 s and
   returned 503 *"high demand"* / 504 *"deadline exceeded"* errors several times (all recovered by the retry logic),
   while retrieval took **~25 ms** (dense only) to **~350 ms** (hybrid + reranker, measured in the ablation).
   Retrieval is about 1–5% of the time a user waits.

### Step 7 — Fitting the evaluation into a laptop: two-phase scoring

The evaluation process grew to **5.5 GB of RAM** and stalled. It held four models at once (embedder, reranker and
two NLI models) on a 4 GB GPU that another desktop app was also using, so Windows spilled GPU memory into slow
shared RAM. A second "prefetch" process we started to speed things up crashed with the same paging-file error.

Fix: the classic batch-job pattern of **don't hold what you don't need**.
- **Phase 1** (retrieval models only): retrieve, call Gemini, store the answer *and the excerpts it saw*.
- **Phase 2**: unload the retrieval models (`cache_clear()` + `torch.cuda.empty_cache()`), load only the NLI models
  in fp16 (half the memory, re-verified 8/8 on the checker tests), and score every stored answer.
Bonus: phase 2 can be re-run any time (`--rescore`) to improve the checker without touching the API.

### Step 8 — The result that looked wrong (and was)

The first complete scoring said the **upgraded** system was *less* grounded (0.35 vs 0.45) and that 78% of its answers
contained a hallucination. The answers were short, cited, and looked right when read. When a number contradicts
what you can see with your own eyes, **suspect the measurement first**.

Reading the flagged claims showed obvious false alarms: *"Training took 3.5 days on 8 P100 GPUs"* (almost verbatim
in the paper) scored an entailment of 0.05.

- First suspect: we had just switched the NLI models to fp16. A controlled test (same inputs, fp32 vs fp16) gave
  identical numbers, so **not the cause**. Good to rule out, rather than "fix" the wrong thing.
- Real cause: **NLI models are trained on 1–3 sentence premises.** We were feeding ~220-word windows. Given a long
  premise, the model says "neutral" even when the claim sits inside it word for word. Our earlier sanity test passed
  only because its context happened to be 3 sentences long. **The test didn't match production conditions.**
- Fix (the published *SummaC* approach): split each excerpt into sentences and score the claim against every
  1-, 2- and 3-sentence window, keeping the best. We also stopped treating "the excerpts do not contain X" as a
  factual claim (it's an abstention).
- Re-check: **8/8 real answers that were false alarms are now correctly "grounded"**, and 7/8 synthetic cases.
  The miss is instructive: "the encoder **of the Transformer** has 6 layers" is not literally entailed by "The
  encoder is composed of 6 identical layers" from a paper titled "Attention Is All You Need". NLI is *strict about
  named entities*: it errs towards flagging, which is the safe direction for a hallucination detector.
- Known residual weakness: math notation (`1/sqrt(d_k)` vs `1/√dk`) and claims that combine facts from several
  far-apart sentences can still be under-scored.

Then all 80 answers were re-scored offline (0 API calls).

### Step 9 — Two more measurement fixes from reading the output

Reading the remaining flags found two more issues. Both affected the two systems equally:

1. **Sentences *about the excerpts* were scored as claims about the paper.** The grounded prompt allows one
   sentence like *"The excerpts do contain results for other benchmarks such as MMLU."* That is a statement about
   what was retrieved, not a fact about the paper, so it is now skipped like an abstention.
2. **The "abstained" regex was too loose.** It fired on phrases like "not explicitly stated" inside real answers.
   We replaced it with the rubric's own definition for unanswerable questions (RUBRIC.md):
   **2** = says it's not in the document and asserts nothing unsupported; **1** = says so, *then* adds
   outside-knowledge content; **0** = answers as if the document said it. We also count answerable questions where
   the system explicitly refused ("false refusals").

### Step 10 — Final end-to-end results (40 questions × 2 systems, same Gemini model)

Script: `eval/run_generation_eval.py` → `eval/results/generation_summary.json` (per-answer records in
`eval/results/generation_eval.jsonl`; the retrieved paper text is kept out of git for licence reasons).

| Metric | Original design | Upgraded | Change |
|---|---|---|---|
| Right evidence retrieved (hit@k) | 71.4% | **94.3%** | +23 pts |
| Key-fact coverage (answerable) | 77.7% | **81.7%** | +4 pts |
| Groundedness (share of answer sentences supported by the excerpts) | 0.82 | **0.92** | +0.10 |
| Answers containing ≥1 unsupported claim | 50.0% | **14.3%** | −36 pts |
| Unanswerable questions: rubric handling score (0–2) | 1.0 | **2.0** | perfect |
| False refusals on answerable questions | 9 / 35 | **1 / 35** | −8 |
| Input tokens per question (mean) | 10,525 | **2,751** | −74% |
| Output tokens per answer (mean) | 292 | **65** | −78% |
| Cost per 1,000 questions (paid-tier list price) | $3.89 | **$0.99** | −75% |
| Gemini latency p50 | 20.5 s | **7.4 s** | see caveat |
| Answer length (words) | 190 | **39** | |

**What this means:**

- **The old prompt was the main hallucination source.** Its unanswerable answers all followed the same pattern:
  *"This specific information is not available in the provided context. Detailed answer based on relevant
  knowledge: …"* It technically refused and then filled the space with general knowledge. That earned rubric
  score 1 on every unanswerable question. The grounded prompt refused cleanly 5/5.
- **The old system also refused questions it *could* have answered (9 of 35)**, because its single dense search
  missed the evidence; then it fell back on outside knowledge. Better retrieval removed most of these (1 left,
  and that one was a partial answer: it gave the training details and said the layer count wasn't in the excerpts).
- **Shorter is not lazier.** Answers went from 190 to 39 words, but key-fact coverage *went up*. The old answers
  were long because the prompt demanded "maximum detail", not because they contained more facts.
- **Cost:** about 75% cheaper per question at the same model price, almost entirely from sending 2.7k instead of
  10.5k input tokens. Retrieval runs locally, so indexing a PDF costs **0 API calls**; the original design would
  have spent embedding requests on every chunk.

**Caveats (say these in an interview, because they make you more credible, not less):**
- 40 questions and 5 papers is a small eval. One question is ~3 points, so treat small differences as noise. The
  large effects (hallucination 50% → 14%, tokens −74%, retrieval +23 pts) are well beyond that.
- Groundedness is an automatic NLI proxy that we validated on hand-made cases and by reading every flagged claim
  of the final system (5 remain: e.g. `n_ctx = 2048` notation, one figure combined from two places, and a hedge
  phrase). It is not a human judgement.
- Latency depends heavily on Gemini's load. During the "before" run the model was overloaded (many 503/504
  retries), so the latency gap is real in direction but not precise in size. Fewer input and output tokens do make
  calls faster.

---

## 6. Final summary: what changed, in one table

| Area | Before | After |
|---|---|---|
| Status | Broken (retired Gemini models, removed LangChain APIs) | Working on `gemini-3.5-flash-lite`, pinned deps |
| Chunking | 10,000 chars, cut anywhere, no pages | 512-token sentence-aligned chunks with page ranges + title header |
| Retrieval | Dense only, k=4 | BM25 + dense → RRF → cross-encoder rerank, k=5, history-aware |
| Prompt | "Maximum detail", fall back on general knowledge | Grounded, cite pages, explicit "not in the document" |
| Storage | One global pickle index | Per-document JSON/NumPy index keyed by file hash |
| Observability | None | Exact tokens, cost, per-stage latency per request; `/chat/stats` |
| Reliability | No timeout, raw errors to the browser | 60 s timeout, back-off retries, friendly errors, response cache |
| Quality evidence | None | Retrieval ablation + before/after eval + 13 automated tests |

## 7. Future work (in order of expected value)

1. **Bigger eval set** (100+ questions, more document types such as tables, slides and scanned PDFs) to shrink noise.
2. **Table-aware parsing** (e.g. Docling) for numeric questions that live in tables.
3. **Corrective RAG loop** (LangGraph): if the reranker's best score is low, rewrite the query or answer "not
   found" without calling the LLM at all, which saves cost on off-topic questions.
4. **Streaming answers** to cut perceived latency.
5. **Second judge** (RAGAS/DeepEval with a different LLM) to cross-check the NLI groundedness numbers.

Lesson for interviews: **evaluate your evaluator.** An automatic metric you have not sanity-checked is just a
random number with a nice name.
