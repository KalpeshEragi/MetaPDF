"""Aggregate raw benchmark output into eval/results/baseline_results.json and baseline_summary.csv.

Inputs : eval/questions.jsonl, results/rag_baseline_raw.jsonl, results/rag_ingestion.json, results/judgments.jsonl (judge scores),
         results/summarization_baseline_raw.json, results/summary_judgments.json, results/multi_document_raw.json, environment.json
Rule   : nothing is invented. Missing inputs yield nulls, never defaults.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import scoring

EVAL = Path(__file__).resolve().parent
RES = EVAL / "results"
J = lambda p: json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
JL = lambda p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []

questions = {q["id"]: q for q in JL(EVAL / "questions.jsonl")}
raw = {r["id"]: r for r in JL(RES / "rag_baseline_raw.jsonl")}
judg = {j["id"]: j for j in JL(RES / "judgments.jsonl")}
ingestion = J(RES / "rag_ingestion.json") or {}
ok = {i: r for i, r in raw.items() if "error" not in r}
errors = {i: r.get("error") for i, r in raw.items() if "error" in r}

rows = []  # (scope, metric, value)


def put(scope, metric, value):
    rows.append((scope, metric, value))


def desc_put(scope, name, vals):
    d = scoring.describe(vals)
    for k, v in d.items():
        put(scope, f"{name}.{k}", v)
    return d


R = {"questions_total": len(questions), "questions_run_ok": len(ok), "questions_errored": errors}

# ------------------------------------------------------------------ retrieval
ans = [r for r in ok.values() if r["is_answerable"]]
ret = {
    "n_answerable": len(ans),
    "hit_at_k_gold_evidence_retrieval_rate": round(sum(bool(r["gold_hit_any"]) for r in ans) / len(ans), 4) if ans else None,
    "recall_at_k_mean": round(sum(r["gold_recall"] for r in ans) / len(ans), 4) if ans else None,
    "full_evidence_rate": round(sum(bool(r["gold_full"]) for r in ans) / len(ans), 4) if ans else None,
    "mrr": round(sum((1 / r["first_gold_rank"]) if r["first_gold_rank"] else 0 for r in ans) / len(ans), 4) if ans else None,
    "k": sorted({r["k_returned"] for r in ok.values()}),
}
by_doc = defaultdict(list)
by_type = defaultdict(list)
for r in ans:
    by_doc[r["document"]].append(r)
    by_type[r["question_type"]].append(r)
ret["by_document"] = {d: {"n": len(v), "hit": round(sum(bool(x["gold_hit_any"]) for x in v) / len(v), 3),
                          "recall": round(sum(x["gold_recall"] for x in v) / len(v), 3)} for d, v in by_doc.items()}
ret["by_question_type"] = {t: {"n": len(v), "hit": round(sum(bool(x["gold_hit_any"]) for x in v) / len(v), 3),
                               "recall": round(sum(x["gold_recall"] for x in v) / len(v), 3)} for t, v in by_type.items()}
R["retrieval"] = ret
for k, v in ret.items():
    if not isinstance(v, (dict, list)):
        put("retrieval", k, v)

# ------------------------------------------------------------------ tokens & latency (all questions that ran)
allr = list(ok.values())
tok = {
    "context_tokens_est_chars_div_4": desc_put("tokens", "context_tokens_est", [r["context_tokens_est_chars_div_4"] for r in allr]),
    "context_chars": desc_put("tokens", "context_chars", [r["context_chars"] for r in allr]),
    "input_tokens_provider": desc_put("tokens", "input_tokens_provider", [r["input_tokens_provider"] for r in allr]),
    "output_tokens_provider": desc_put("tokens", "output_tokens_provider", [r["output_tokens_provider"] for r in allr]),
    "total_tokens_provider": desc_put("tokens", "total_tokens_provider", [r["input_tokens_provider"] + r["output_tokens_provider"] for r in allr]),
    "llm_calls_per_question": desc_put("tokens", "llm_calls", [r["n_llm_calls"] for r in allr]),
    "embedding_calls_per_question": desc_put("tokens", "embedding_calls", [r["n_embedding_calls"] for r in allr]),
    "answer_words": desc_put("tokens", "answer_words", [r["answer_words"] for r in allr]),
}
lat = {}
for key in ("retrieval_total", "load_vector_store", "similarity_search_incl_query_embedding", "llm_chain_call", "llm_prompt_eval",
            "llm_decode", "total_pipeline"):
    lat[key] = desc_put("latency_s", key, [r["latency_s"][key] for r in allr])
R["tokens"], R["latency_seconds"] = tok, lat
R["generation_truncated_by_cap"] = [r["id"] for r in allr if "length" in (r.get("done_reason") or [])]
R["thinking_present_any"] = any(r.get("thinking_present") for r in allr)

# ------------------------------------------------------------------ answer quality
q = {}
comp, corr, faith, hall = [], [], [], []
claims = [0, 0, 0]
handled = []
per_q = []
for qid, r in ok.items():
    qq = questions[qid]
    row = {"id": qid, "document": qq["document"], "type": qq["question_type"], "answerable": qq["is_answerable"]}
    j = judg.get(qid)
    if qq["is_answerable"]:
        cov, hit = scoring.key_fact_coverage(r["answer"], qq["key_facts"])
        row.update({"key_fact_coverage": round(cov, 3), "completeness": scoring.completeness_score(cov)})
        comp.append(row["completeness"])
        if j:
            row.update({"correctness": j["correctness"], "faithfulness": j["faithfulness"], "hallucination": j["hallucination"]})
            corr.append(j["correctness"]); faith.append(j["faithfulness"]); hall.append(bool(j["hallucination"]))
            claims[0] += j["n_claims"]; claims[1] += j["n_supported"]; claims[2] += j["n_unsupported"]
    else:
        row["abstained_auto"] = scoring.abstained(r["answer"])
        if j:
            row.update({"handling": j["handling"], "hallucination": j["hallucination"]})
            handled.append(j["handling"]); hall.append(bool(j["hallucination"]))
    per_q.append(row)
mean = lambda v: round(sum(v) / len(v), 3) if v else None
q["answerable_n"] = len(comp)
q["completeness_mean_0_2"] = mean(comp)
q["completeness_distribution"] = {str(k): comp.count(k) for k in (0, 1, 2)}
q["correctness_mean_0_2"] = mean(corr)
q["correctness_distribution"] = {str(k): corr.count(k) for k in (0, 1, 2)} if corr else None
q["faithfulness_mean_0_2"] = mean(faith)
q["faithfulness_distribution"] = {str(k): faith.count(k) for k in (0, 1, 2)} if faith else None
q["claims_total"], q["claims_supported"], q["claims_unsupported"] = claims if corr else (None, None, None)
q["claim_support_rate"] = round(claims[1] / claims[0], 4) if corr and claims[0] else None
q["hallucination_rate_all_judged"] = round(sum(hall) / len(hall), 4) if hall else None
q["unanswerable_n"] = len(handled)
q["unanswerable_handling_mean_0_2"] = mean(handled)
q["unanswerable_handling_distribution"] = {str(k): handled.count(k) for k in (0, 1, 2)} if handled else None
q["unanswerable_abstained_auto"] = sum(r.get("abstained_auto", False) for r in per_q if not r["answerable"])
fu = [r for r in per_q if r["type"] == "follow_up"]
q["followup"] = {"n": len(fu), "completeness_mean": mean([r["completeness"] for r in fu if r.get("completeness") is not None]),
                 "correctness_mean": mean([r["correctness"] for r in fu if r.get("correctness") is not None])}
q["by_type"] = {}
for t in sorted({r["type"] for r in per_q}):
    s = [r for r in per_q if r["type"] == t and r["answerable"]]
    if s:
        q["by_type"][t] = {"n": len(s), "completeness_mean": mean([r["completeness"] for r in s]),
                           "correctness_mean": mean([r["correctness"] for r in s if "correctness" in r])}
R["quality"], R["per_question"] = q, per_q
for k, v in q.items():
    if not isinstance(v, (dict, list)):
        put("quality", k, v)

# ------------------------------------------------------------------ ingestion
R["ingestion"] = ingestion
for d, v in ingestion.items():
    for k in ("pages", "raw_chars", "n_chunks", "extraction_seconds", "embedding_prompt_tokens_provider_reported",
              "index_build_seconds_total", "index_size_bytes"):
        put(f"ingestion.{d}", k, v.get(k))

# ------------------------------------------------------------------ summarization / multi-doc / environment
summ = J(RES / "summarization_baseline_raw.json")
sj = J(RES / "summary_judgments.json")
if summ:
    S = {"as_shipped": summ.get("_as_shipped"), "compat": summ.get("_compat"), "papers": {}}
    for d, v in summ.items():
        if d.startswith("_"):
            continue
        s = {k: v[k] for k in v if k not in ("page_records", "combined_summary", "extract_pages_ui_messages")}
        if sj and d in sj:
            s["key_point_judgment"] = sj[d]
        S["papers"][d] = s
        for k in ("pages_summarized", "total_chunks", "bart_calls", "second_pass_calls", "in_tokens", "out_tokens",
                  "summarization_seconds", "compression_ratio_summary_over_source_words", "combined_summary_words"):
            put(f"summarization.{d}", k, v.get(k))
        if sj and d in sj:
            put(f"summarization.{d}", "key_point_coverage_per_page_summaries", sj[d].get("coverage_page_summaries"))
            put(f"summarization.{d}", "key_point_coverage_combined", sj[d].get("coverage_combined"))
    R["summarization"] = S
env = J(EVAL / "environment.json")
R["environment_checks"] = {k: v["status"] for k, v in (env or {}).get("checks", {}).items()}
R["multi_document"] = (J(EVAL / "multi_document_baseline.json") or {}).get("summary")

(RES / "baseline_results.json").write_text(json.dumps(R, indent=1, ensure_ascii=False), encoding="utf-8")
with (RES / "baseline_summary.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["scope", "metric", "value"])
    w.writerows(rows)
print("wrote baseline_results.json and baseline_summary.csv;", len(rows), "rows")
