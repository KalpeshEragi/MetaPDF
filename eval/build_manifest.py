"""Build eval/corpus/manifest.json from the PDFs in eval/corpus/pdfs (kept out of git).

Text extraction deliberately mirrors production: PyPDF2 PdfReader.extract_text() per page; a page is
'sparse' (would trigger OCR in ocr_processor.hybrid_extract_pages) if its whitespace-collapsed text is <= 50 chars.
Per-page text is cached in eval/corpus/text/ (gitignored) so gold evidence can be re-verified.
"""
import hashlib
import json
import re
import time
from pathlib import Path

from PyPDF2 import PdfReader

ROOT = Path(__file__).resolve().parent
PDFS = ROOT / "corpus" / "pdfs"
TEXT = ROOT / "corpus" / "text"
TEXT.mkdir(parents=True, exist_ok=True)

META = {
    "attention_is_all_you_need": dict(
        title="Attention Is All You Need", authors="Vaswani, Shazeer, Parmar, Uszkoreit, Jones, Gomez, Kaiser, Polosukhin",
        year=2017, url="https://arxiv.org/abs/1706.03762", pdf_url="https://arxiv.org/pdf/1706.03762",
        topic="Transformer architecture; machine translation (WMT14 EN-DE/EN-FR)", bucket="5-15"),
    "rag_lewis": dict(
        title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        authors="Lewis, Perez, Piktus, Petroni, Karpukhin, Goyal, Kuttler, Lewis, Yih, Rocktaschel, Riedel, Kiela",
        year=2020, url="https://arxiv.org/abs/2005.11401", pdf_url="https://arxiv.org/pdf/2005.11401",
        topic="Retrieval-augmented generation; open-domain QA, generation, fact verification", bucket="15-30"),
    "constitutional_ai": dict(
        title="Constitutional AI: Harmlessness from AI Feedback", authors="Bai et al. (Anthropic)", year=2022,
        url="https://arxiv.org/abs/2212.08073", pdf_url="https://arxiv.org/pdf/2212.08073",
        topic="AI-feedback alignment: supervised critique-revision and RL from AI feedback", bucket="30-50"),
    "gpt3_few_shot": dict(
        title="Language Models are Few-Shot Learners", authors="Brown et al. (OpenAI)", year=2020,
        url="https://arxiv.org/abs/2005.14165", pdf_url="https://arxiv.org/pdf/2005.14165",
        topic="GPT-3 scaling and few-shot in-context learning; many benchmark tables", bucket="50-80"),
    "palm": dict(
        title="PaLM: Scaling Language Modeling with Pathways", authors="Chowdhery et al. (Google)", year=2022,
        url="https://arxiv.org/abs/2204.02311", pdf_url="https://arxiv.org/pdf/2204.02311",
        topic="540B dense LM trained with Pathways; benchmarks, reasoning, memorization, bias", bucket="80+"),
}

docs = []
for stem, meta in META.items():
    path = PDFS / f"{stem}.pdf"
    raw = path.read_bytes()
    t0 = time.perf_counter()
    reader = PdfReader(str(path))
    pages = []
    for p in reader.pages:
        pages.append(p.extract_text() or "")
    secs = time.perf_counter() - t0
    clean = [re.sub(r"\s+", " ", t).strip() for t in pages]
    sparse = [i + 1 for i, t in enumerate(clean) if len(t) <= 50]
    kind = "text" if not sparse else ("scanned" if len(sparse) == len(clean) else "mixed")
    (TEXT / f"{stem}.json").write_text(json.dumps(pages), encoding="utf-8")
    docs.append(dict(
        id=stem, **meta, file=f"corpus/pdfs/{stem}.pdf", sha256=hashlib.sha256(raw).hexdigest(),
        file_size_bytes=len(raw), pages=len(pages), extracted_chars=sum(len(t) for t in pages),
        extracted_words=sum(len(t.split()) for t in pages), sparse_pages=sparse, pdf_type=kind,
        extraction_seconds_pypdf2=round(secs, 3), license_note="arXiv PDF; redistribution not assumed - kept out of git"))
    print(stem, len(pages), "pages", sum(len(t) for t in pages), "chars", kind)

(ROOT / "corpus" / "manifest.json").write_text(
    json.dumps({"created": time.strftime("%Y-%m-%d"), "extractor": "PyPDF2 PdfReader.extract_text (as in production)",
                "documents": docs}, indent=2), encoding="utf-8")
