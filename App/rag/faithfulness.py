"""Local hallucination check with an NLI (Natural Language Inference) model.

Idea: split the answer into sentences ("claims"). For each claim ask the NLI model "does any retrieved excerpt
ENTAIL this sentence?". A claim with no supporting excerpt is *unsupported* — a likely hallucination.

* groundedness = supported claims / all claims          (1.0 = every sentence backed by the document)
* hallucinated  = answer has at least one unsupported claim

This runs fully offline (no Gemini quota) and the generator never grades itself. It is an automatic proxy, not a
human judgement: NLI models can miss paraphrases that span several excerpts, so treat small differences with care.
"""
from __future__ import annotations

import re

from . import models
from .chunking import split_sentences

NLI_MODELS = ("cross-encoder/nli-deberta-v3-base", "cross-encoder/nli-deberta-v3-small")
_CITE = re.compile(r"\[(?:p|pp)\.[^\]]*\]")
_LEAD = re.compile(r"^(based on|according to|as (stated|described|shown|mentioned) in) (the )?(provided |given )?"
                   r"(context|excerpts?|document|text|paper)( provided)?,\s*", re.I)
_SKIP = re.compile(r"(does not contain this information|not available in the provided context|"
                   # statements ABOUT the excerpts ("The excerpts do contain results for X") are not claims about the
                   # paper; they come from the prompt's "say what related information the excerpts contain" rule
                   r"^(however, )?(the )?(provided )?(document )?(excerpts?|context|text|document)s? (do |does )?(also )?"
                   r"(contain|include|provide|mention|discuss|detail|cover)s?\b|"
                   r"(excerpts?|document|context|text)s? (do|does) not (contain|mention|include|provide|specify)|"
                   r"(is|are) not (mentioned|provided|included|specified|stated) in the (provided )?(excerpts?|document|context)|"
                   r"^(based on|according to) the (provided )?(context|excerpts?|document)[,:]?$)", re.I)


def _claims(answer: str) -> list[str]:
    text = re.sub(r"\s+([.,;:!?])", r"\1", _CITE.sub("", answer))   # "layers [p. 3]." -> "layers."
    text = re.sub(r"[*#`>$]+|\\(?:mathrm|text|textbf)\b", " ", text)  # strip markdown and LaTeX math markers
    text = re.sub(r"\\([a-zA-Z]+)", r"\1", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*([-•]|\d+[.)])\s*", "", line).strip()
        for s in split_sentences(line):
            s = _LEAD.sub("", s.strip())         # "Based on the provided context, X" -> "X" (the claim is X)
            s = s[:1].upper() + s[1:]
            if len(s.split()) >= 4 and not _SKIP.search(s) and not s.endswith(":"):
                out.append(s)
    return out


def _windows(text: str, sizes: tuple[int, ...] = (1, 2, 3)) -> list[str]:
    """Sentence-level premises (SummaC-style). NLI models are trained on 1–3 sentence premises and answer "neutral"
    for a 200-word premise even when it contains the claim verbatim, so we slide 1-, 2- and 3-sentence windows over
    the excerpt and keep the best-scoring one."""
    sents = split_sentences(text) or [text]
    out = []
    for n in sizes:
        out += [" ".join(sents[i:i + n]) for i in range(max(1, len(sents) - n + 1))]
    return list(dict.fromkeys(out))


def _best_entailment(model_name: str, claims: list[str], premises: list[str], device: str) -> list[float]:
    model = models.nli(model_name, device)
    ent = {v.lower(): k for k, v in model.model.config.id2label.items()}["entailment"]
    pairs = [(p, c) for c in claims for p in premises]
    probs = model.predict(pairs, apply_softmax=True, batch_size=32, show_progress_bar=False)
    n_p = len(premises)
    return [float(max(probs[i * n_p:(i + 1) * n_p, ent])) for i in range(len(claims))]


def score(answer: str, contexts: list[str], threshold: float = 0.5, device: str = "auto", title: str | None = None) -> dict:
    claims = _claims(answer)
    if not claims:
        return {"n_claims": 0, "n_supported": 0, "groundedness": None, "hallucinated": False, "unsupported": []}
    # The reader knows which document the excerpts come from, so the judge gets the title too; otherwise
    # "The Transformer encoder has 6 layers" would not be entailed by an excerpt that only says "The encoder ...".
    prefix = f"From the document \"{title}\": " if title else ""
    premises = [prefix + w for c in contexts for w in _windows(c)]
    # Two-model ensemble: single NLI models are brittle to tiny wording changes ("model" vs "models"), so a claim
    # counts as supported if EITHER model finds an excerpt that entails it. Fabricated facts fail both.
    best = [max(a, b) for a, b in zip(*(_best_entailment(m, claims, premises, device) for m in NLI_MODELS))]
    supported = [b >= threshold for b in best]
    return {"n_claims": len(claims), "n_supported": sum(supported),
            "groundedness": round(sum(supported) / len(claims), 4), "hallucinated": not all(supported),
            "unsupported": [{"claim": c, "max_entailment": round(b, 3)} for c, b, s in zip(claims, best, supported)
                            if not s]}
