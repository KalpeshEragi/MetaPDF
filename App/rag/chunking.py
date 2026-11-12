"""Chunking: turn pages into retrievable pieces that remember their page numbers.

Two strategies:
* ``sentence`` (new): pack whole sentences into chunks of at most ``chunk_tokens`` tokens (counted with the embedding
  model's own tokenizer), carrying ``chunk_overlap_tokens`` of trailing sentences into the next chunk so facts that sit
  on a boundary are not lost.
* ``legacy_chars`` (old behaviour, kept only for the before/after comparison): 10,000-character chunks with 1,000
  characters overlap over the concatenated text, exactly like the original ``chat_app.py``.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import asdict, dataclass
from typing import Callable

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'])")


@dataclass
class Chunk:
    id: int
    text: str           # what the user/LLM sees
    page_start: int     # 1-based
    page_end: int
    n_tokens: int
    header: str = ""    # contextual header used for embedding/BM25 only

    @property
    def index_text(self) -> str:
        return f"{self.header}\n{self.text}" if self.header else self.text

    @property
    def pages_label(self) -> str:
        return f"p. {self.page_start}" if self.page_start == self.page_end else f"pp. {self.page_start}-{self.page_end}"

    def to_dict(self) -> dict:
        return asdict(self)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return [s for s in _SENT.split(text) if s.strip()] if text else []


def sentence_chunks(pages: list[str], count_tokens: Callable[[str], int], chunk_tokens: int,
                    overlap_tokens: int) -> list[Chunk]:
    units: list[tuple[str, int, int]] = []  # (sentence, page, tokens)
    for pno, page in enumerate(pages, 1):
        for s in split_sentences(page):
            n = count_tokens(s)
            if n <= chunk_tokens:
                units.append((s, pno, n))
                continue
            words = s.split()                       # very long "sentence" (tables, references): split by words
            step = max(20, int(len(words) * chunk_tokens / n * 0.9))
            for i in range(0, len(words), step):
                piece = " ".join(words[i:i + step])
                units.append((piece, pno, count_tokens(piece)))

    chunks: list[Chunk] = []
    cur: list[tuple[str, int, int]] = []
    cur_tok = 0

    def emit():
        chunks.append(Chunk(id=len(chunks), text=" ".join(u[0] for u in cur), page_start=cur[0][1],
                            page_end=cur[-1][1], n_tokens=sum(u[2] for u in cur)))

    for u in units:
        if cur and cur_tok + u[2] > chunk_tokens:
            emit()
            keep, t = [], 0
            for x in reversed(cur):
                if t + x[2] > overlap_tokens:
                    break
                keep.insert(0, x)
                t += x[2]
            cur, cur_tok = keep, t
        cur.append(u)
        cur_tok += u[2]
    if cur:
        emit()
    return chunks


def legacy_char_chunks(pages: list[str], count_tokens: Callable[[str], int], size: int, overlap: int) -> list[Chunk]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    starts, text = [], ""
    for p in pages:                                  # original code concatenated pages with no separator
        starts.append(len(text))
        text += p
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap, add_start_index=True)
    out = []
    for i, d in enumerate(splitter.create_documents([text])):
        s = d.metadata["start_index"]
        e = s + len(d.page_content)
        out.append(Chunk(id=i, text=d.page_content, page_start=bisect.bisect_right(starts, s),
                         page_end=bisect.bisect_right(starts, max(s, e - 1)), n_tokens=count_tokens(d.page_content)))
    return out


def add_headers(chunks: list[Chunk], title: str) -> None:
    for c in chunks:
        c.header = f"{title} | {c.pages_label}"
