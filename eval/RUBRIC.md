# MetaPDF evaluation rubric (FIXED — do not change between CURRENT and IMPROVED runs)

Defined 2026-10-04, before any benchmark run. Any future change to this file must be recorded as a new rubric version and
all comparisons re-run under both versions.

## A. RAG answers — scores are 0–2 per dimension
Inputs to the judge: question, system answer, gold answer, gold evidence quotes (source text). Never the retrieved context.

| Dimension | Method | 2 | 1 | 0 |
|---|---|---|---|---|
| **Completeness** | **Automatic**: fraction of `key_facts` (regex alternatives in `questions.jsonl`) found in the answer | all key facts | ≥ 50% of key facts | < 50% |
| **Correctness** | **Judge** (see below) | every claim that touches the gold answer is correct and no key fact is contradicted | partially correct: at least one key fact right but another missing-by-error/wrong, or right answer with a material error | wrong, contradicts gold, or non-answer |
| **Faithfulness** | **Judge** against gold evidence + gold answer (claims about the paper not supported by the evidence are "unsupported") | all paper-specific claims supported | 1–2 minor unsupported paper-specific details | major unsupported or contradicted claims |

Per answer the judge also records: `n_claims` (atomic paper-specific factual claims), `n_supported`, `n_unsupported`,
`hallucination` (true if the answer asserts a paper-specific fact that is contradicted by or absent from the source and is material),
and free-text notes for every score < 2.

### Unanswerable questions (`is_answerable == false`) — "handling" score 0–2
- 2 = states the information is not in the document (any wording) **and** does not assert fabricated paper-specific results.
- 1 = states it is not in the document **but** then supplies outside-knowledge or invented specifics presented as an answer about the paper.
- 0 = does not abstain and gives an answer (fabricated).
Automatic helper: `ABSTAIN` regex in `eval/scoring.py` (reported separately as `abstained`); the judge's handling score is authoritative.
Unanswerable items are excluded from correctness/completeness means and reported only under "unanswerable handling".

### Follow-up questions
Asked with the earlier question + its **gold answer** as conversation history (so follow-up handling is isolated from earlier errors).
Scored with the same dimensions. The production system never sends history to the LLM, so the history is only *offered* to it
by the harness exactly the way the UI would (as a prior turn in the session) — it changes nothing unless the system uses it.

### Judge
The judge must differ from the generation model (Qwen3.5:4B). Judge = the reviewing engineer/assistant reading each answer against
the gold evidence (recorded in `eval/results/judgments.jsonl` with notes). Automated pieces (completeness, abstention regex,
retrieval hit tests) are reproducible; judge scores are the human-in-the-loop part. Important failures are inspected manually.
A second human spot-check of ≥ 10 random items is recommended before treating small differences (< 0.2 mean points) as real.

## B. Retrieval metrics (answerable questions only)
Evidence is "retrieved" if its verbatim quote (whitespace-normalised) is a substring of a retrieved chunk's text.
- **Hit@k** (a.k.a. gold-evidence retrieval rate): fraction of questions with ≥ 1 gold quote in the retrieved chunks.
- **Recall@k**: mean over questions of (gold quotes found in the union of retrieved chunks) / (gold quotes).
- **Full-evidence rate**: fraction of questions where all gold quotes are found.
- **MRR**: 1 / rank of the first retrieved chunk (rank by similarity order, 1-based) that contains any gold quote; 0 if none.
k is whatever the system returns (production default k = 4).

## C. Summarization
- Per paper, 5–10 fixed key points are defined in `eval/summary_keypoints.json` **before** running the summarizer.
- **Key-point coverage** = covered points / total points, judged against the produced per-page summaries and the combined summary
  separately (a point is covered if the summary states it substantively; partial = 0.5).
- Also recorded: factual errors, missing major findings, duplication, unsupported content, compression ratio (summary words / source words),
  BART call counts, second-pass calls, token counts, runtime.

## D. Statistics
For latency/token distributions: mean, p50, p90, p95, min, max (nearest-rank percentiles on all measured questions).

## E. Fixed configuration of the "current" system under test (baseline-compat-v1)
Production code unchanged. The only substitutions are the unavailable components, enumerated in `05_baseline_environment.md`:
LangChain legacy import paths aliased to their relocated equivalents; Google embedding/LLM replaced by local Ollama
`nomic-embed-text` and `qwen3.5:4b` (non-thinking), as mandated by the project owner for all experiments.
