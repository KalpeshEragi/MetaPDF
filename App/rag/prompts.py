"""Prompts. The legacy prompt is kept verbatim only so the evaluation can compare old vs new behaviour."""
from __future__ import annotations

NOT_FOUND = "The document does not contain this information."

GROUNDED_SYSTEM = f"""You are MetaPDF, an assistant that answers questions about ONE uploaded document.
Rules:
1. Use ONLY the numbered excerpts provided. Never use outside knowledge, even if you know the topic.
2. After each factual sentence, cite the page(s) it came from, e.g. [p. 3] or [pp. 4-5].
3. If the excerpts do not contain the answer, reply exactly: "{NOT_FOUND}" You may add one sentence saying what
   related information the excerpts do contain.
4. Be concise and specific: 1-5 sentences, keep exact numbers, names and units as written.
5. Earlier conversation turns are given only to resolve references like "it" or "that model"."""


def format_context(retrieved) -> str:
    return "\n\n".join(f"[Excerpt {r.rank} | {r.chunk.pages_label}]\n{r.chunk.text}" for r in retrieved)


def grounded_prompt(question: str, retrieved, history: list[dict] | None = None) -> str:
    parts = [f"Document excerpts:\n{format_context(retrieved)}"]
    if history:
        turns = "\n".join(f"User: {h['question']}\nAssistant: {h['answer'][:600]}" for h in history)
        parts.append(f"Earlier conversation:\n{turns}")
    parts.append(f"Question: {question}\nAnswer:")
    return "\n\n".join(parts)


LEGACY_TEMPLATE = """
    Answer the question with maximum detail and thoroughness using information from the provided context.

   If the specific information requested is not present in the context, clearly indicate this by stating: "This specific information is not available in the provided context." Then proceed to offer a DETAILED ANSWER based on relevant knowledge about the subject.

   Maintain a formal, authoritative tone throughout the response. Prioritize accuracy, completeness, and comprehensive explanations while organizing information logically and coherently.

   Include all relevant details, examples, and technical specifics from the context when available. Leave no aspect of the question unexplored.

   Context:
   {context}

   Question:
   {question}

   Answer:
    """


def legacy_prompt(question: str, retrieved) -> str:
    # load_qa_chain("stuff") joined documents with blank lines and no page labels
    return LEGACY_TEMPLATE.format(context="\n\n".join(r.chunk.text for r in retrieved), question=question)
