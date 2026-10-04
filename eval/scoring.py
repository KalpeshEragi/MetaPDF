"""Deterministic scoring helpers shared by all benchmark scripts (rubric: eval/RUBRIC.md)."""
import math
import re

ABSTAIN = re.compile(
    r"(not (available|mentioned|provided|stated|specified|reported|discussed|included|contained|found|present|addressed|covered)"
    r"|no (information|mention|data|reference|details?)"
    r"|(does not|doesn.t|do not|did not|didn.t) (mention|contain|provide|report|discuss|include|specify|appear|address|cover)"
    r"|cannot (be )?(found|determined|answered|located)|unable to (find|determine|locate)"
    r"|(isn.t|is not|aren.t|are not|wasn.t|was not) (mentioned|available|provided|present|in the (provided )?(context|document|paper|text)))",
    re.I)
PRODUCTION_ABSTAIN_PHRASE = "This specific information is not available in the provided context"


def key_fact_coverage(answer: str, key_facts):
    """Fraction of key facts covered; each fact is a list of regex alternatives (any match counts)."""
    if not key_facts:
        return None
    hit = [any(re.search(alt, answer, re.I) for alt in fact) for fact in key_facts]
    return sum(hit) / len(hit), hit


def completeness_score(cov):
    """Fixed mapping from RUBRIC.md: 2 = all key facts, 1 = >= 50 %, 0 = otherwise."""
    if cov is None:
        return None
    return 2 if cov >= 0.999 else (1 if cov >= 0.5 else 0)


def abstained(answer: str) -> bool:
    return bool(ABSTAIN.search(answer)) or PRODUCTION_ABSTAIN_PHRASE.lower() in answer.lower()


def percentile(sorted_vals, p):
    """Nearest-rank percentile (p in 0..100)."""
    if not sorted_vals:
        return None
    k = max(1, math.ceil(p / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def describe(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0}
    return {"n": len(v), "mean": round(sum(v) / len(v), 4), "p50": percentile(v, 50), "p90": percentile(v, 90),
            "p95": percentile(v, 95), "min": v[0], "max": v[-1]}
