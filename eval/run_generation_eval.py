"""Before/after answer evaluation with Gemini (the only script that spends API quota).

Systems (same Gemini model for both, because the original model was retired):
  before = original design: 10k-char chunks, dense-only k=4, "maximum detail + fall back on general knowledge" prompt
  after  = upgraded design: 320-token page-aware chunks, hybrid BM25+dense, reranker, k=5, grounded prompt with citations

Scored automatically (no LLM judge, no extra quota):
  * completeness  — key facts from questions.jsonl found in the answer (RUBRIC.md A)
  * abstention    — unanswerable questions: did it say the info is not in the document (RUBRIC.md A)
  * groundedness / hallucination — local NLI model checks every answer sentence against the retrieved excerpts
  * tokens (from Gemini usage_metadata), $ cost at paid-tier prices, latency

Resumable: results are appended per question; all Gemini responses are disk-cached, so re-running costs 0 requests.
If the daily quota runs out the script stops cleanly; run it again later to continue.

Run:  <venv>/python eval/run_generation_eval.py [--systems before after] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time

from rag_common import LEGACY, RES, UPGRADED, history_for, load_manifest, load_questions, retrieval_metrics, EVAL

import scoring
from App.rag import faithfulness
from App.rag.llm import QuotaExhausted
from App.rag.pipeline import RAGService

SYSTEMS = {"before": LEGACY, "after": UPGRADED}
OUT = RES / "generation_eval.jsonl"


def run(systems: list[str], limit: int | None, pause: float):
    qs = load_questions()[: limit or None]
    by_id = {q["id"]: q for q in load_questions()}
    manifest = load_manifest()
    done = set()
    if OUT.exists():
        done = {(r["system"], r["id"]) for r in map(json.loads, OUT.read_text(encoding="utf-8").splitlines())
                if "error" not in r}
    failures = 0
    for name in systems:
        svc = RAGService(SYSTEMS[name])
        doc_ids = {}
        for q in qs:
            if (name, q["id"]) in done:
                continue
            d = q["document"]
            if d not in doc_ids:
                doc_ids[d] = svc.ingest((EVAL / manifest[d]["file"]).read_bytes(), title=manifest[d]["title"])["doc_id"]
            hist = history_for(q, by_id)
            try:
                res = svc.ask(doc_ids[d], q["question"], hist)
            except QuotaExhausted as e:
                print(f"\nGemini quota exhausted at {name}/{q['id']} — re-run later to resume.\n{str(e)[:300]}")
                return False
            ans = res["answer"]
            rec = {"system": name, "id": q["id"], "document": d, "type": q["question_type"],
                   "answerable": q["is_answerable"], "question": q["question"], "answer": ans,
                   "usage": res["usage"], "latency_ms": res["latency_ms"], "citations": res["citations"],
                   "contexts": [r["text"] for r in res["retrieved"]]}
            rec["retrieval"] = retrieval_metrics(q, [r["text"] for r in res["retrieved"]],
                                                 [_pages(r["pages"]) for r in res["retrieved"]])
            if q["is_answerable"]:
                cov = scoring.key_fact_coverage(ans, q["key_facts"])
                rec["key_fact_coverage"] = cov[0] if cov else None
                rec["completeness"] = scoring.completeness_score(cov[0]) if cov else None
                rec["abstained"] = scoring.abstained(ans) or res["abstained"]
            else:
                rec["abstained"] = scoring.abstained(ans) or res["abstained"]
            rec["faithfulness"] = None          # scored in phase 2 (rescore) so NLI models never share memory
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            u = res["usage"]
            print(f"{name:6s} {q['id']:8s} in={u['input_tokens']:6d} out={u['output_tokens']:5d} "
                  f"cached={u['cached']} llm_ms={res['latency_ms']['llm']} "
                  f"cov={rec.get('key_fact_coverage')} abst={rec['abstained']}", flush=True)
            if not u["cached"]:
                time.sleep(pause)
    if failures:
        print(f"{failures} question(s) skipped — run again to fill them in (answers so far are cached).")
    return failures == 0


def free_retrieval_models():
    import gc
    from App.rag import models
    models.embedder.cache_clear()
    models.reranker.cache_clear()
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def rescore(only_missing: bool = False):
    """Phase 2: hallucination scores for stored answers with the local NLI checker (0 API calls)."""
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    manifest = load_manifest()
    t0 = time.time()
    for i, r in enumerate(rows):
        if only_missing and r.get("faithfulness"):
            continue
        r["faithfulness"] = faithfulness.score(r["answer"], r["contexts"], title=manifest[r["document"]]["title"])
        print(f"scored {i + 1}/{len(rows)} {r['system']} {r['id']} grounded={r['faithfulness']['groundedness']} "
              f"({time.time() - t0:.0f}s)", flush=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"rescored {len(rows)} answers")


def _pages(label: str) -> tuple[int, int]:
    nums = label.split()[-1].split("-")
    return int(nums[0]), int(nums[-1])


def pct(vals, p):
    v = sorted(vals)
    return scoring.percentile(v, p) if v else None


REFUSAL = re.compile(r"(this specific information is not available in the provided context|"
                     r"the document does not contain this information|(excerpts?|document) (do|does) not contain)", re.I)


def unanswerable_handling(r) -> int:
    """RUBRIC.md A: 2 = says it's not in the document and asserts nothing unsupported; 1 = says so but then adds
    outside-knowledge / unsupported content; 0 = answers as if it were in the document."""
    if not REFUSAL.search(r["answer"]):
        return 0
    return 2 if not r["faithfulness"]["unsupported"] else 1


def summarize():
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    summary = {}
    for name in ("before", "after"):
        R = [r for r in rows if r["system"] == name]
        if not R:
            continue
        ans = [r for r in R if r["answerable"]]
        una = [r for r in R if not r["answerable"]]
        fa = [r["faithfulness"] for r in R if r["faithfulness"]["n_claims"]]
        inp = [r["usage"]["input_tokens"] for r in R]
        out = [r["usage"]["output_tokens"] for r in R]
        cost = [r["usage"]["cost_usd"] or 0 for r in R]
        lat = [r["latency_ms"]["total"] for r in R if not r["usage"]["cached"]]
        summary[name] = {
            "n_questions": len(R), "n_answerable": len(ans), "n_unanswerable": len(una),
            "key_fact_coverage_mean": round(statistics.mean(r["key_fact_coverage"] for r in ans), 4),
            "completeness_score_mean_0_2": round(statistics.mean(r["completeness"] for r in ans), 3),
            "answerable_with_explicit_refusal": sum(bool(REFUSAL.search(r["answer"])) for r in ans),
            "unanswerable_refused": sum(bool(REFUSAL.search(r["answer"])) for r in una),
            "unanswerable_handling_mean_0_2": round(statistics.mean(unanswerable_handling(r) for r in una), 3),
            "groundedness_mean": round(statistics.mean(f["groundedness"] for f in fa), 4),
            "answers_with_unsupported_claim_rate": round(sum(f["hallucinated"] for f in fa) / len(fa), 4),
            "unsupported_claims_total": sum(f["n_claims"] - f["n_supported"] for f in fa),
            "claims_total": sum(f["n_claims"] for f in fa),
            "evidence_hit_rate": round(statistics.mean(float(r["retrieval"]["hit"]) for r in ans), 4),
            "evidence_recall": round(statistics.mean(r["retrieval"]["recall"] for r in ans), 4),
            "input_tokens_mean": round(statistics.mean(inp)), "input_tokens_p95": pct(inp, 95),
            "output_tokens_mean": round(statistics.mean(out)), "output_tokens_p95": pct(out, 95),
            "cost_usd_per_question": round(statistics.mean(cost), 7),
            "cost_usd_per_1000_questions": round(1000 * statistics.mean(cost), 3),
            "latency_ms_p50": pct(lat, 50), "latency_ms_p95": pct(lat, 95), "latency_samples": len(lat),
            "answer_words_mean": round(statistics.mean(len(r["answer"].split()) for r in R), 1),
        }
    (RES / "generation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="*", default=["before", "after"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--pause", type=float, default=4.0, help="seconds between live Gemini calls (RPM limits)")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--rescore", action="store_true", help="recompute hallucination scores only (no API calls)")
    a = ap.parse_args()
    if a.rescore:
        rescore()
    elif not a.summary_only:
        if run(a.systems, a.limit, a.pause):
            free_retrieval_models()
            rescore(only_missing=True)
    summarize()
