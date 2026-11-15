# Contributing to MetaPDF

Thanks for helping out. This project's rule is simple: **if a change claims to make answers better, show the
numbers.** Everything else is ordinary good practice.

## Set up

```bash
git clone https://github.com/<your-username>/MetaPDF.git
cd MetaPDF
python -m venv venv
venv\Scripts\activate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `env/.env` and add a `GOOGLE_API_KEY`. You only need it to chat or to run the generation
eval; the tests and the retrieval ablation run without one.

## Before you open a pull request

1. **Tests pass:** `python -m pytest tests -q`. No network, GPU or API key needed.
2. **New behaviour has a test** in `tests/test_rag.py`. Keep tests fast and offline, and use the `FakeService`
   pattern for routes.
3. **Retrieval, chunking or prompt changes include numbers.** Run `python eval/run_retrieval_ablation.py` (no API
   calls) and paste the relevant rows before and after into the PR. For prompt changes, also run
   `python eval/run_generation_eval.py`. It is cached and resumable, so re-runs are free.
4. **Settings go in `App/rag/config.py`**, with an environment-variable override if users might want to change it.
   If the setting changes how documents are indexed, add it to `index_signature()` so old indexes rebuild.

## Ground rules

- **Never commit secrets** (`env/.env`), the eval PDFs, or anything under `data/`. They are git-ignored; keep it
  that way.
- **Don't commit retrieved paper text.** The eval writes full records to `eval/results/_work/` (ignored) and a slim
  copy without excerpts to `eval/results/`.
- **Don't use pickle for stored indexes.** Use JSON and NumPy only.
- **Use [Conventional Commits](https://www.conventionalcommits.org/):** `feat:`, `fix:`, `docs:`, `test:`, `eval:`,
  `chore:`. One logical change per commit.
- **Branch names** like `feat/query-rewriting` or `fix/empty-pdf-error`.

## Good first issues

- Stream the Gemini answer to the chat UI token by token.
- Support scanned PDFs in the chat by reusing `App/ocr_processor.py` during ingestion.
- Add a query-rewriting step and measure it in the ablation.
- Grow the eval set beyond 5 papers and 40 questions. More questions mean tighter error bars.
- Multi-document chat (ask across several uploaded PDFs).

## Reporting bugs

Open an issue with:
- what you did and what you expected;
- the error text from the terminal;
- your OS, Python version, and whether you're on CPU or GPU.

Leave out your API key.
