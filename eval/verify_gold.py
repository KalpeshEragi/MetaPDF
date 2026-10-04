"""Mechanically verify the gold set against the extracted PDF page text.

Checks: (1) every evidence quote is a verbatim substring (whitespace-normalised) of the cited page;
(2) every `absent_terms` entry appears nowhere in the document; (3) structural fields and follow-up links.
Exit code 1 if anything fails. Needs eval/corpus/text/*.json (created by build_manifest.py).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
norm = lambda s: re.sub(r"\s+", " ", s).strip()
pages = {}
bad = 0
qs = [json.loads(l) for l in (ROOT / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
ids = {q["id"] for q in qs}
for q in qs:
    d = q["document"]
    if d not in pages:
        pages[d] = [norm(t) for t in json.loads((ROOT / "corpus" / "text" / f"{d}.json").read_text(encoding="utf-8"))]
    for key in ("id", "document", "question", "question_type", "gold_answer", "gold_pages", "gold_sections",
                "gold_evidence", "is_answerable"):
        if key not in q:
            print("MISSING FIELD", q["id"], key); bad += 1
    if q["is_answerable"]:
        if not q["gold_evidence"]:
            print("NO EVIDENCE", q["id"]); bad += 1
        for e in q["gold_evidence"]:
            if norm(e["quote"]) not in pages[d][e["page"] - 1]:
                print("QUOTE NOT FOUND", q["id"], "p", e["page"], "|", e["quote"][:90]); bad += 1
    else:
        for t in q["absent_terms"]:
            hits = [i + 1 for i, p in enumerate(pages[d]) if t.lower() in p.lower()]
            if hits:
                print("ABSENT TERM PRESENT", q["id"], t, hits); bad += 1
    if q.get("followup_of") and q["followup_of"] not in ids:
        print("BAD FOLLOWUP LINK", q["id"]); bad += 1
from collections import Counter
print(len(qs), "questions;", Counter(q["document"] for q in qs))
print(Counter(q["question_type"] for q in qs))
print("answerable:", sum(q["is_answerable"] for q in qs), "unanswerable:", sum(not q["is_answerable"] for q in qs))
print("FAILURES:", bad)
sys.exit(1 if bad else 0)
