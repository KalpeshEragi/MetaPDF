"""Fast unit tests for the RAG building blocks and the chat route (no network, no GPU, no API key needed).

Run:  <venv>/python -m pytest tests -q
"""
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from App.rag.chunking import legacy_char_chunks, sentence_chunks, split_sentences  # noqa: E402
from App.rag.faithfulness import _claims  # noqa: E402
from App.rag.llm import estimate_cost  # noqa: E402
from App.rag.retrieve import rrf  # noqa: E402

words = lambda s: len(s.split())


def test_split_sentences_keeps_numbers():
    s = split_sentences("The model has 6 layers. It reached 28.4 BLEU! Training took 3.5 days.")
    assert s == ["The model has 6 layers.", "It reached 28.4 BLEU!", "Training took 3.5 days."]


def test_sentence_chunks_respect_budget_and_pages():
    pages = [" ".join(f"Page one sentence {i} here." for i in range(40)),
             " ".join(f"Page two sentence {i} here." for i in range(40))]
    chunks = sentence_chunks(pages, words, chunk_tokens=50, overlap_tokens=10)
    assert all(c.n_tokens <= 50 for c in chunks)
    assert chunks[0].page_start == 1 and chunks[-1].page_end == 2
    assert any(c.page_start == 1 and c.page_end == 2 for c in chunks)      # a chunk spanning the page break
    # overlap: the last sentence of chunk i reappears at the start of chunk i+1
    assert chunks[1].text.split(".")[0] in chunks[0].text


def test_overlong_sentence_is_split():
    pages = [" ".join(["word"] * 500) + "."]
    chunks = sentence_chunks(pages, words, chunk_tokens=100, overlap_tokens=0)
    assert len(chunks) >= 5 and all(c.n_tokens <= 100 for c in chunks)


def test_legacy_chunks_map_pages():
    pages = ["a" * 6000, "b" * 6000, "c" * 6000]
    chunks = legacy_char_chunks(pages, words, size=10000, overlap=1000)
    assert chunks[0].page_start == 1 and chunks[-1].page_end == 3


def test_rrf_rewards_agreement():
    fused = rrf([[1, 2, 3], [3, 1, 4]], k=60)
    assert fused[0] == 1 and set(fused) == {1, 2, 3, 4}


def test_claims_ignore_citations_and_abstentions():
    ans = "The encoder has 6 layers [p. 3]. The document does not contain this information.\n- Uses residual connections around sublayers [pp. 3-4]."
    claims = _claims(ans)
    assert claims == ["The encoder has 6 layers .", "Uses residual connections around sublayers ."] or \
        [c.replace(" .", ".") for c in claims] == ["The encoder has 6 layers.", "Uses residual connections around sublayers."]


def test_claims_skip_meta_statements_and_strip_latex_and_openers():
    ans = ("Based on the provided context, the encoder has $N = 6$ identical layers [p. 3]. "
           "The excerpts do contain results for other benchmarks such as MMLU. "
           "The provided document excerpts do not contain the model dimension.")
    assert _claims(ans) == ["The encoder has N = 6 identical layers."]


def test_sentence_windows_are_short_premises():
    from App.rag.faithfulness import _windows
    w = _windows("One fact here. Two facts here. Three facts here. Four facts here.")
    assert "One fact here." in w and "One fact here. Two facts here." in w
    assert max(len(x.split(". ")) for x in w) <= 3


def test_title_skips_arxiv_licence_and_joins_wrapped_lines():
    from App.rag.extract import guess_title
    p1 = ("Provided proper attribution is provided, Google hereby grants permission to\n"
          "reproduce the tables and figures in this paper solely for use in journalistic or\n"
          "scholarly works.\nAttention Is All You Need\nAshish Vaswani\nGoogle Brain\navaswani@google.com")
    assert guess_title([p1], "fallback") == "Attention Is All You Need"
    p2 = "Retrieval-Augmented Generation for\nKnowledge-Intensive NLP Tasks\nPatrick Lewis"
    assert guess_title([p2], "fallback") == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    assert guess_title(["lowercase body text only."], "file") == "file"
    assert guess_title([p1], "x", metadata_title="Microsoft Word - draft.docx") == "Attention Is All You Need"


def test_cost_estimate():
    assert estimate_cost("gemini-3.5-flash-lite", 1_000_000, 0) == pytest.approx(0.30)
    assert estimate_cost("gemini-3.5-flash-lite", 0, 1_000_000) == pytest.approx(2.50)
    assert estimate_cost("unknown-model", 10, 10) is None


# ---------------------------------------------------------------- web route with a fake service
class FakeService:
    def __init__(self):
        from App.rag.config import RAGConfig
        self.cfg = RAGConfig(data_dir=ROOT / "eval" / "results" / "_work" / "test_data")

    def ingest(self, data, filename=""):
        return {"doc_id": "abc", "title": "T", "pages": 1, "n_chunks": 2, "reused_existing_index": False, "seconds": 0.1}

    def ask(self, doc_id, question, history):
        return {"answer": "<script>x</script> Six layers [p. 3].", "abstained": False, "citations": ["p. 3"],
                "retrieved": [{"rank": 1, "pages": "p. 3", "text": "six layers"}],
                "usage": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0, "cached": False},
                "latency_ms": {"total": 1.0}}


@pytest.fixture
def client(monkeypatch):
    from flask import Flask

    import App.chat_app as chat_mod
    monkeypatch.setattr(chat_mod, "_service", FakeService())
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.secret_key = "test"
    app.register_blueprint(chat_mod.chat_app)
    return app.test_client()


def test_question_before_upload_is_rejected(client):
    r = client.post("/chat/", data={"user_question": "hi"})
    assert r.status_code == 400 and "upload" in r.get_json()["message"].lower()


def test_upload_then_ask_returns_citations_and_usage(client):
    r = client.post("/chat/", data={"pdf_files": (io.BytesIO(b"%PDF-1.4"), "x.pdf")},
                    content_type="multipart/form-data")
    assert r.get_json()["status"] == "success"
    r = client.post("/chat/", data={"user_question": "How many layers?"})
    d = r.get_json()
    assert d["citations"] == ["p. 3"] and d["usage"]["input_tokens"] == 10


def test_non_pdf_upload_rejected(client):
    r = client.post("/chat/", data={"pdf_files": (io.BytesIO(b"x"), "x.docx")}, content_type="multipart/form-data")
    assert r.status_code == 400
