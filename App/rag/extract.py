"""PDF text extraction (one place for the whole app).

Returns text per page so every chunk can remember which page(s) it came from — that is what makes page citations
possible. pypdf is the maintained successor of the deprecated PyPDF2.
"""
from __future__ import annotations

import hashlib
import io
import re

from pypdf import PdfReader

_WS = re.compile(r"[ \t\r\f\v]+")


def clean_page(text: str) -> str:
    text = text.replace("­", "")                      # soft hyphens
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)            # de-hyphenate words broken across lines
    text = _WS.sub(" ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def extract_pages(pdf: bytes | io.BytesIO) -> list[str]:
    data = pdf if isinstance(pdf, (bytes, bytearray)) else pdf.read()
    reader = PdfReader(io.BytesIO(data))
    return [clean_page(p.extract_text() or "") for p in reader.pages]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_NOT_TITLE = re.compile(r"(arxiv|copyright|licen[cs]e|permission|attribution|preprint|proceedings|conference|"
                        r"journal|university|institute|@|http|doi|abstract|vol\.|pp\.)", re.I)
_SMALL = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "with", "is", "via", "from", "by", "at", "as"}


def _looks_like_title(line: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", line)
    if not (2 <= len(words) <= 18) or _NOT_TITLE.search(line) or line.rstrip().endswith((".", ",", ";")):
        return False
    caps = sum(w[0].isupper() for w in words if w.lower() not in _SMALL)
    big = sum(1 for w in words if w.lower() not in _SMALL)
    return big > 0 and caps / big >= 0.75                  # Title Case Like This


def guess_title(pages: list[str], fallback: str, metadata_title: str | None = None) -> str:
    """Document title for contextual chunk headers: PDF metadata if sensible, else the first Title-Case line on page 1
    (skipping licence/affiliation boilerplate such as arXiv permission notices), else the file name."""
    if metadata_title and len(metadata_title.split()) >= 2 and not _NOT_TITLE.search(metadata_title) \
            and not re.search(r"\.(docx?|pdf|tex)$|^untitled|^microsoft", metadata_title, re.I):
        return metadata_title.strip()[:120]
    lines = [l.strip() for l in (pages[0].splitlines()[:25] if pages else [])]
    for i, line in enumerate(lines):
        if _looks_like_title(line):
            # titles often wrap: "Retrieval-Augmented Generation for" / "Knowledge-Intensive NLP Tasks"
            if i + 1 < len(lines) and line.split()[-1].lower() in _SMALL and _looks_like_title(lines[i + 1]):
                line = f"{line} {lines[i + 1]}"
            return line[:120]
    return fallback


def metadata_title(pdf: bytes) -> str | None:
    try:
        meta = PdfReader(io.BytesIO(pdf)).metadata
        return (meta.title or None) if meta else None
    except Exception:
        return None
