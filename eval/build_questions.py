"""Builds eval/questions.jsonl (gold QA set). Edit THIS file, then re-run, then run verify_gold.py.

Method (see dev_docs/metapdf_audit/05_baseline_benchmark.md):
  * Questions + gold answers were written by reading the extracted paper text (not generated blind by an LLM).
  * Every gold_evidence entry is a verbatim substring (whitespace-normalised) of the cited PDF page's extracted text;
    verify_gold.py enforces this mechanically.
  * Unanswerable questions list `absent_terms` that verify_gold.py confirms appear nowhere in the document.
  * Pages are 1-based PDF page indices (not printed page numbers).
  * Follow-up questions carry `followup_of`; their conversation history is the earlier question plus its GOLD answer
    (so follow-up handling is measured independently of earlier-answer quality).
"""
import json
from pathlib import Path

Q = []


def add(doc, qid, qtype, question, answer, sections, evidence, answerable=True, followup_of=None, absent=None, note=None):
    Q.append(dict(
        id=qid, document=doc, question=question, question_type=qtype, gold_answer=answer,
        gold_pages=sorted({e[0] for e in evidence}), gold_sections=sections,
        gold_evidence=[{"page": p, "quote": t} for p, t in evidence],
        is_answerable=answerable, followup_of=followup_of, absent_terms=absent or [], notes=note))


# ----------------------------------------------------------------------------- Attention Is All You Need
D = "attention_is_all_you_need"
add(D, "att-01", "factual_lookup", "How many identical layers make up the encoder stack of the Transformer?",
    "N = 6 identical layers.", ["3.1 Encoder and Decoder Stacks"],
    [(3, "The encoder is composed of a stack of N= 6 identical layers")])
add(D, "att-02", "numerical_detail", "What BLEU score did the big Transformer reach on the WMT 2014 English-to-German task, and how long did training take on what hardware?",
    "28.4 BLEU; training took 3.5 days on 8 P100 GPUs.", ["6.1 Machine Translation"],
    [(8, "establishing a new state-of-the-art BLEU score of 28.4"), (8, "Training took 3.5days on 8P100 GPUs")])
add(D, "att-03", "methodology", "Why does the Transformer scale the dot products by 1/sqrt(d_k) in scaled dot-product attention?",
    "For large d_k the dot products grow large in magnitude, pushing the softmax into regions with extremely small gradients; scaling counteracts this.",
    ["3.2.1 Scaled Dot-Product Attention"],
    [(4, "pushing the softmax function into regions where it has extremely small gradients")])
add(D, "att-04", "multi_paragraph_reasoning", "How does self-attention compare with recurrent layers in sequential operations and maximum path length, and why does path length matter?",
    "Self-attention needs O(1) sequential operations and has O(1) maximum path length between any two positions; recurrent layers need O(n) for both. Shorter paths between input and output positions make long-range dependencies easier to learn.",
    ["4 Why Self-Attention"],
    [(6, "a self-attention layer connects all positions with a constant number of sequentially executed operations"),
     (6, "Recurrent O(n·d2) O(n) O(n)"), (6, "the easier it is to learn long-range dependencies")])
add(D, "att-05", "cross_section_reasoning", "How long and on what hardware was the base model trained, and what were its number of layers and model dimension?",
    "Base model: 100,000 steps (about 12 hours) on one machine with 8 NVIDIA P100 GPUs; 6 encoder/decoder layers (N=6) with d_model = 512.",
    ["5.2 Hardware and Schedule", "3.1 Encoder and Decoder Stacks"],
    [(7, "We trained the base models for a total of 100,000 steps or 12 hours"), (7, "We trained our models on one machine with 8 NVIDIA P100 GPUs"),
     (3, "produce outputs of dimension dmodel = 512"), (3, "The encoder is composed of a stack of N= 6 identical layers")])
add(D, "att-06", "results_limitations", "In the model-variation ablation, how did single-head attention compare with the best multi-head setting, and what happened with too many heads?",
    "Single-head attention was 0.9 BLEU worse than the best setting, and quality also drops off with too many heads.",
    ["6.2 Model Variations"],
    [(9, "While single-head attention is 0.9 BLEU worse than the best setting, quality also drops off with too many heads")])
add(D, "att-07", "unanswerable", "What BLEU score did the Transformer obtain on the WMT 2019 English-to-German task?",
    "Not answerable: the paper reports WMT 2014 results only; WMT 2019 is never mentioned.", [], [], answerable=False,
    absent=["WMT 2019", "WMT 2018", "WMT 2016"])
add(D, "att-08", "follow_up", "And what did that same big model score on English-to-French?",
    "41.8 BLEU (abstract and Table 2). Note: one sentence in Section 6.1 of the same paper says 41.0; graders should accept 41.8 and may credit mention of the discrepancy.",
    ["Abstract", "6.1 Machine Translation"],
    [(1, "establishes a new single-model state-of-the-art BLEU score of 41.8"), (8, "Transformer (big) 28.4 41.8")],
    followup_of="att-02", note="Paper contains an internal inconsistency (41.8 in abstract/Table 2 vs 41.0 in 6.1 text).")

# ----------------------------------------------------------------------------- RAG (Lewis et al.)
D = "rag_lewis"
add(D, "rag-01", "factual_lookup", "Which model does RAG use as its generator and how many parameters does it have?",
    "BART-large, a pre-trained seq2seq transformer with 400M parameters.", ["2.3 Generator: BART"],
    [(3, "a pre-trained seq2seq transformer [ 58] with 400M parameters")])
add(D, "rag-02", "numerical_detail", "On Natural Questions, what exact-match scores did RAG-Token and RAG-Sequence achieve on the test set?",
    "RAG-Token 44.1 and RAG-Sequence 44.5 exact match.", ["4.1 Open-domain Question Answering (Table 1)"],
    [(6, "RAG-Token 44.1 55.2/66.1 45.5 50.0 RAG-Seq. 44.5 56.8/ 68.0 45.2 52.2")])
add(D, "rag-03", "methodology", "How does RAG-Sequence differ from RAG-Token in how retrieved documents are used?",
    "RAG-Sequence uses the same retrieved document to generate the complete output sequence (per-sequence marginalization); RAG-Token lets different retrieved documents be responsible for different tokens (per-token marginalization).",
    ["2.1 Models"],
    [(3, "The RAG-Sequence model uses the same retrieved document to generate the complete sequence"),
     (2, "or a per-token basis (where different documents are responsible for different tokens)")])
add(D, "rag-04", "multi_paragraph_reasoning", "What advantage does RAG have over parametric-only models for keeping knowledge current, and how did the authors demonstrate it?",
    "Its non-parametric memory (the document index) can be replaced at test time without retraining ('index hot-swapping'). They compared a December 2016 Wikipedia index with the December 2018 index on 82 world leaders who changed: RAG answered 70% correctly with the 2016 index for 2016 leaders and 68% with the 2018 index for 2018 leaders, but only 12% and 4% with mismatched indices.",
    ["4.5 Additional Results: Index hot-swapping"],
    [(7, "Index hot-swapping An advantage of non-parametric memory models like RAG is that knowledge can be easily updated at test time"),
     (7, "We prepare a list of 82 world leaders who had changed"),
     (8, "RAG answers 70% correctly using the 2016 index for 2016 world leaders and 68% using the 2018 index for 2018 world leaders"),
     (8, "Accuracy with mismatched indices is low (12% with the 2018 index and 2016 leaders, 4% with the 2016 index and 2018 leaders)")])
add(D, "rag-05", "cross_section_reasoning", "How is RAG's retriever initialised, how is the retrieved passage supplied to the generator, and how many documents k are retrieved during training?",
    "The retriever is initialised from a pre-trained DPR bi-encoder (which also builds the document index); the retrieved content z is simply concatenated with the input x for BART; during training k is 5 or 10 (test-time k set using dev data).",
    ["2.2 Retriever: DPR", "2.3 Generator: BART", "3 Experiments"],
    [(3, "We use a pre-trained bi-encoder from DPR to initialize our retriever and to build the document index"),
     (3, "we simply concatenate them"), (4, "We consider k2f5;10gfor training and set kfor test time using dev data")])
add(D, "rag-06", "results_limitations", "What societal downsides or risks do the authors acknowledge for RAG?",
    "Wikipedia (or any external knowledge source) will probably never be entirely factual and free of bias, and as a language model RAG might be used to generate abuse, faked or misleading content, to impersonate others, or to automate spam/phishing; advanced language models may also automate jobs.",
    ["Broader Impact"],
    [(10, "Wikipedia, or any potential external knowledge source, will probably never be entirely factual and completely devoid of bias"),
     (10, "it might be used to generate abuse, faked or misleading content in the news or on social media")])
add(D, "rag-07", "unanswerable", "What exact-match accuracy did RAG achieve on HotpotQA?",
    "Not answerable: HotpotQA is not evaluated or mentioned in the paper.", [], [], answerable=False, absent=["HotpotQA"])
add(D, "rag-08", "follow_up", "And on TriviaQA, which of the two RAG variants scored higher?",
    "RAG-Sequence scored higher in both TriviaQA columns: 56.8 vs 55.2 and 68.0 vs 66.1 (the second column is the TQA Wiki test set used for comparison with T5).",
    ["4.1 Open-domain Question Answering (Table 1)"],
    [(6, "RAG-Token 44.1 55.2/66.1 45.5 50.0 RAG-Seq. 44.5 56.8/ 68.0 45.2 52.2")], followup_of="rag-02")

# ----------------------------------------------------------------------------- Constitutional AI
D = "constitutional_ai"
add(D, "cai-01", "factual_lookup", "How many harmlessness principles did the authors write, and how are they used during revision?",
    "16 principles; one is randomly sampled at each revision step of each red-team prompt.", ["3.1 Method"],
    [(8, "We have written a total of 16 different principles"), (8, "They are randomly sampled at each revision step of each red team prompt")])
add(D, "cai-02", "numerical_detail", "How many red-team prompts were used for the supervised stage and how many were human-written versus model-generated?",
    "42,496 human-written plus 140,335 model-generated = 182,831 red-team prompts.", ["3.2 Datasets and Training"],
    [(8, "we collected 42,496 human-written prompts"),
     (8, "and generated a further 140,335 prompts by few-shot prompting a pre- trained model, giving a total of 182,831")])
add(D, "cai-03", "methodology", "What are the two stages of the Constitutional AI process?",
    "A supervised learning stage (sample from an initial model, generate self-critiques and revisions, finetune on revised responses) and a reinforcement learning stage (a model judges which of two samples is better, a preference model is trained on these AI preferences, and RL uses it as reward: RLAIF).",
    ["Abstract", "1.2 The Constitutional AI Approach"],
    [(1, "In the supervised phase we sample from an initial model, then generate self-critiques and revisions"),
     (1, "use a model to evaluate which of the two samples is better")])
add(D, "cai-04", "multi_paragraph_reasoning", "How does the RL-from-AI-feedback stage obtain harmlessness preference labels and how does it differ from standard RLHF?",
    "Instead of crowdworkers, an independent feedback model (typically a pretrained LM) is shown the conversation, a response pair and a principle and picks the more harmless response; the remainder of the pipeline (preference model training and RL) is exactly the same as RLHF.",
    ["4.1 Method (RL from AI Feedback)"],
    [(10, "instead of asking crowdworkers to provide comparison labels for harmlessness, we simply present the same task to an independent model, called the feedback model (typically a pretrained LM)"),
     (10, "the remainder of the training pipeline (i.e., preference model training and RL) is exactly the same as RLHF")])
add(D, "cai-05", "cross_section_reasoning", "How many AI-generated harmlessness comparisons were used to train the RL preference model, and how does that number relate to the supervised-stage red-team prompts?",
    "182,831 constitutionally-generated harmlessness comparisons (alongside 135,296 human helpfulness comparisons) - one comparison per SL-CAI prompt, which equals the 182,831 total red-team prompts of the supervised stage (42,496 human + 140,335 model-generated).",
    ["4.2 Datasets and Training", "3.2 Datasets and Training"],
    [(11, "135,296 HF helpfulness comparisons, and 182,831 constitutionally- generated harmlessness comparisons (one comparison generated for each SL-CAI prompt)"),
     (8, "giving a total of 182,831")])
add(D, "cai-06", "results_limitations", "What dual-use concern do the authors raise about constitutional methods?",
    "The methods lower the barrier to training AI models that behave as their creators intend, so they also make it easier to train pernicious systems.",
    ["6.2 Broader Impacts"],
    [(16, "the ideas discussed in this work have a dual use"),
     (16, "we lower the barrier to training AI models that behave in ways their creators intend. This means that these methods also make it easier to train pernicious systems")])
add(D, "cai-07", "unanswerable", "What MMLU score did the Constitutional AI models achieve?",
    "Not answerable: MMLU is not evaluated or mentioned in the paper.", [], [], answerable=False, absent=["MMLU"])
add(D, "cai-08", "follow_up", "And how many helpfulness prompts were used in that same stage?",
    "135,296 human-written helpfulness prompts; no model-generated helpfulness prompts were used.", ["3.2 Datasets and Training"],
    [(8, "For helpfulness prompts, we collected a total of 135,296 human-written ones, and did not use any model-generated examples")],
    followup_of="cai-02")

# ----------------------------------------------------------------------------- GPT-3
D = "gpt3_few_shot"
add(D, "gpt3-01", "factual_lookup", "How many parameters does GPT-3 have and how many model sizes did the authors train?",
    "175 billion parameters; 8 model sizes ranging from 125 million to 175 billion parameters.", ["2.1 Model and Architectures"],
    [(8, "we train 8 different sizes of model, ranging over three orders of magnitude from 125 million parameters to 175 billion parameters"),
     (1, "an autoregressive language model with 175 billion parameters")])
add(D, "gpt3-02", "numerical_detail", "What accuracy did GPT-3 achieve on TriviaQA in the zero-, one- and few-shot settings?",
    "64.3% zero-shot, 68.0% one-shot, 71.2% few-shot.", ["3.1.2 Closed Book Question Answering"],
    [(13, "On TriviaQA, we achieve 64.3% in the zero-shot setting, 68.0% in the one-shot setting, and 71.2% in the few-shot setting")])
add(D, "gpt3-03", "methodology", "How do the zero-shot, one-shot and few-shot settings differ in GPT-3's evaluation, and how many demonstrations does few-shot typically use?",
    "Zero-shot: only a natural-language instruction, no demonstrations. One-shot: exactly one demonstration. Few-shot: as many demonstrations as fit in the context window, typically 10 to 100. No gradient updates or fine-tuning in any setting.",
    ["1 Introduction"],
    [(5, "(typically 10 to 100)"), (5, "we allow only one demonstration"),
     (5, "no demonstrations are allowed and only an instruction in natural language is given to the model")])
add(D, "gpt3-04", "cross_section_reasoning", "What context window do all GPT-3 models use and how does it constrain the number K of few-shot examples?",
    "All models use a context window of n_ctx = 2048 tokens; K is typically set to 10-100 because that is how many examples fit in the context window.",
    ["2 Approach", "2.1 Model and Architectures"],
    [(8, "All models use a context window of nctx= 2048 tokens"),
     (6, "We typically set Kin the range of 10 to 100 as this is how many examples can")])
add(D, "gpt3-05", "results_limitations", "What SuperGLUE average did few-shot GPT-3 reach and how does it compare with fine-tuned BERT-Large and the fine-tuned state of the art?",
    "Few-shot GPT-3 scored 71.8 on SuperGLUE average, above fine-tuned BERT-Large (69.0) but far below the fine-tuned SOTA (89.0); it needs fewer than eight examples per task to beat BERT-Large.",
    ["3.7 SuperGLUE"],
    [(19, "Fine-tuned SOTA 89.0 91.0 96.9 93.9 94.8 92.5 Fine-tuned BERT-Large 69.0 77.4 83.6 75.7 70.6 71.7 GPT-3 Few-Shot 71.8 76.4 75.6 52.0 92.0 69.0"),
     (20, "GPT-3 requires less than eight total examples per task to outperform")])
add(D, "gpt3-06", "results_limitations", "What limitations do the authors describe for GPT-3 in text synthesis and on some NLP tasks?",
    "Text synthesis: samples sometimes repeat themselves semantically at the document level, lose coherence over long passages, contradict themselves and include non-sequiturs. Tasks: difficulty with common-sense physics, and few-shot performance close to chance on some comparison tasks (WiC, ANLI) and some reading-comprehension tasks.",
    ["5 Limitations"],
    [(33, "it still has notable weaknesses in text synthesis and several NLP tasks"),
     (33, "GPT-3 samples still sometimes repeat themselves semantically at the document level"),
     (33, "it does little better than chance when evaluated one-shot or even few-shot")])
add(D, "gpt3-07", "unanswerable", "What score did GPT-3 achieve on the MMLU benchmark?",
    "Not answerable: MMLU is not evaluated or mentioned in the paper.", [], [], answerable=False, absent=["MMLU", "Massive Multitask"])
add(D, "gpt3-08", "follow_up", "How does that zero-shot result compare with the fine-tuned T5-11B?",
    "The 64.3% zero-shot TriviaQA result already outperforms fine-tuned T5-11B by 14.2% (and a Q&A-tailored span-prediction variant by 3.8%).",
    ["3.1.2 Closed Book Question Answering"],
    [(13, "T5-11B by 14.2%, and also outperforms a version with Q&A tailored span prediction during pre-training by 3.8%")],
    followup_of="gpt3-02")

# ----------------------------------------------------------------------------- PaLM
D = "palm"
add(D, "palm-01", "factual_lookup", "How many parameters does PaLM have, on how many tokens was it trained and on how many TPU chips?",
    "540 billion parameters, trained on 780 billion tokens on 6144 TPU v4 chips.", ["1 Introduction"],
    [(3, "train a 540 billion parameter, densely activated, autoregressive Transformer on 780 billion tokens of high-quality text"),
     (1, "We trained PaLM on 6144 TPU v4 chips using Pathways")])
add(D, "palm-02", "numerical_detail", "What model FLOPs utilization did PaLM 540B achieve and how does it compare with GPT-3 175B, Gopher and Megatron-Turing NLG?",
    "PaLM 540B reached 46.2% MFU versus 21.3% for GPT-3 175B, 32.5% for Gopher 280B and 30.2% for Megatron-Turing NLG 530B.",
    ["4 Training Infrastructure (Table 3)"],
    [(9, "GPT-3 175B V100 21.3% Gopher 280B 4096 TPU v3 32.5% Megatron-Turing NLG 530B 2240 A100 30.2% PaLM 540B 6144 TPU v4 46.2%")])
add(D, "palm-03", "multi_paragraph_reasoning", "What modifications does PaLM make to the standard Transformer architecture?",
    "Decoder-only setup with SwiGLU activations, parallel layers formulation, multi-query attention, RoPE embeddings, shared input-output embeddings, no biases, and a 256k-token SentencePiece vocabulary.",
    ["2 Model Architecture"],
    [(5, "PaLM uses a standard Transformer model architecture (Vaswani et al., 2017) in a decoder-only setup"),
     (5, "We use SwiGLU activations"), (5, "formulation in each Transformer block"), (5, "Multi-Query Attention"),
     (5, "We use RoPE embeddings"), (5, "We share the input and output embedding matrices"),
     (6, "No biases were used in any of the dense kernels or layer norms")])
add(D, "palm-04", "results_limitations", "What was PaLM 540B's average 5-shot MMLU score compared with Chinchilla, and where did it not win?",
    "PaLM 540B averaged 69.3 versus Chinchilla's 67.5 (about +2 points) and outperformed Chinchilla in all MMLU categories except 'Other'.",
    ["6.1.1 Massive Multitask Language Understanding"],
    [(13, "PaLM 540B improves the average score of MMLU benchmark by"),
     (13, "PaLM 540B outperforms the Chinchilla model on all the categories except the category for Other tasks"),
     (13, "PaLM 540B 69.3 77.0 55.6 81.0 69:6")])
add(D, "palm-05", "cross_section_reasoning", "What is the composition of PaLM's pretraining data and roughly what fraction is non-English?",
    "780B tokens: social media conversations 50%, filtered webpages 27%, books 13%, GitHub code 5%, Wikipedia 4%, news 1%; about 22% of training tokens are non-English.",
    ["3 Training Dataset (Table 2)", "6.4 Multilingual Natural Language Generation"],
    [(7, "Social media conversations (multilingual) 50% Filtered webpages (multilingual) 27% Books (English) 13% GitHub (code) 5% Wikipedia (multilingual) 4% News (English) 1%"),
     (33, "22% of the 780B training tokens")])
add(D, "palm-06", "results_limitations", "How does PaLM's memorization rate depend on how often an example appears in the training data?",
    "Examples seen exactly once have a memorization rate of 0.75% for the largest (540B) model, while examples seen more than 500 times are memorized over 40% of the time.",
    ["7 Memorization"],
    [(35, "examples seen exactly once in the training have a memorization rate of 0.75% for our largest model, while examples seen more than 500 times have a memorization rate of over 40%")])
add(D, "palm-07", "unanswerable", "What score did PaLM achieve on the GPQA benchmark?",
    "Not answerable: GPQA is not evaluated or mentioned in the paper.", [], [], answerable=False, absent=["GPQA"])
add(D, "palm-08", "follow_up", "And how are those chips arranged - how many per pod?",
    "Two TPU v4 Pods connected over the data-centre network, with 3072 chips in each Pod attached to 768 hosts (no pipeline parallelism).",
    ["4 Training Infrastructure"],
    [(7, "We use 3072 TPU v4 chips in each Pod attached to 768 hosts"),
     (7, "PaLM 540B is trained over two TPU v4 Pods connected over data center network (DCN)")], followup_of="palm-01")

# --- Fixed key-fact checklists (automatic completeness scoring). Each fact = list of regex alternatives, case-insensitive;
# --- a fact is "covered" if ANY alternative matches the answer. Defined BEFORE any system run; do not edit afterwards.
KEYFACTS = {
    "att-01": [[r"\b6\b|\bsix\b"]],
    "att-02": [[r"28\.4"], [r"3\.5\s*days?|3\.5-day|84 hours|three and a half days"], [r"\b8\s*(nvidia\s*)?p100|eight\s*(nvidia\s*)?p100"]],
    "att-03": [[r"small gradients|vanishing gradient|tiny gradient|gradients? (become|are|get) (very )?small"], [r"softmax"],
               [r"large (values|magnitude)|grow large|large d.?k|large dot products|large in magnitude|growing large"]],
    "att-04": [[r"o\(1\)|constant"], [r"o\(n\)|linear|n sequential"], [r"long.range dependenc"], [r"path"]],
    "att-05": [[r"100,?000\s*steps|100k steps"], [r"12\s*hours"], [r"\b8\s*(nvidia\s*)?p100|eight\s*(nvidia\s*)?p100"], [r"\b512\b"], [r"\b6\b|\bsix\b"]],
    "att-06": [[r"0\.9"], [r"too many heads|many heads|larger number of heads|drops? off|degrad"]],
    "att-08": [[r"41\.8|41\.0"]],
    "rag-01": [[r"bart"], [r"400\s*m\b|400 million"]],
    "rag-02": [[r"44\.1"], [r"44\.5"]],
    "rag-03": [[r"same (retrieved )?document|single document|one document|same retrieved"],
               [r"different documents|each token|per.token|different retrieved documents"]],
    "rag-04": [[r"without (any )?(re)?training|no retraining|without further training|easily updated|replac|swap"], [r"70\s*%"], [r"68\s*%"], [r"12\s*%"], [r"\b4\s*%"]],
    "rag-05": [[r"dpr|bi.?encoder"], [r"concatenat"], [r"5 or 10|\b5\b[^0-9]{1,15}\b10\b|\{5, ?10\}"]],
    "rag-06": [[r"bias"], [r"factual"], [r"abuse|misleading|fake|spam|phishing|impersonat"]],
    "rag-08": [[r"rag.?sequence|rag-seq"], [r"56\.8"], [r"68\.0"]],
    "cai-01": [[r"\b16\b|sixteen"], [r"random"]],
    "cai-02": [[r"42,?496"], [r"140,?335"], [r"182,?831"]],
    "cai-03": [[r"supervis"], [r"reinforcement|\brl\b|rlaif"], [r"critique"], [r"revision|revis"], [r"preference model"]],
    "cai-04": [[r"feedback model|independent model|pretrained (language )?model|language model|ai model"], [r"principle"],
               [r"identical|same as rlhf|exactly the same|same (training )?pipeline|remainder"]],
    "cai-05": [[r"182,?831"], [r"one (comparison )?(per|for each)|each (sl-cai )?prompt|equal|same (number|total|count|as)"], [r"135,?296"]],
    "cai-06": [[r"dual.use"], [r"barrier|easier"], [r"pernicious|harmful|malicious|misuse"]],
    "cai-08": [[r"135,?296"], [r"human.written|no model.generated|not use any model|did not use|without model"]],
    "gpt3-01": [[r"175"], [r"\b8\b|eight"], [r"125 million|125m"]],
    "gpt3-02": [[r"64\.3"], [r"68\.0"], [r"71\.2"]],
    "gpt3-03": [[r"10 to 100|10-100|10–100|ten to a hundred"], [r"no gradient|without gradient|no fine.?tun|without fine.?tun|no (weight )?updates"],
                [r"one demonstration|single demonstration|one example"], [r"instruction"]],
    "gpt3-04": [[r"2048|2,048"], [r"10 to 100|10-100|10–100"]],
    "gpt3-05": [[r"71\.8"], [r"69\.0"], [r"89\.0"]],
    "gpt3-06": [[r"repeat"], [r"coheren"], [r"common.?sense physics|physics"], [r"wic|anli|comparison"]],
    "gpt3-08": [[r"14\.2"], [r"t5"]],
    "palm-01": [[r"540"], [r"780"], [r"6144|6,144"]],
    "palm-02": [[r"46\.2"], [r"21\.3"], [r"32\.5"], [r"30\.2"]],
    "palm-03": [[r"swiglu"], [r"parallel"], [r"multi.?query"], [r"rope|rotary"], [r"shared|share"], [r"no bias|without bias|bias"]],
    "palm-04": [[r"69\.3"], [r"67\.5"], [r"other"]],
    "palm-05": [[r"50\s*%"], [r"27\s*%"], [r"13\s*%"], [r"22\s*%"]],
    "palm-06": [[r"0\.75"], [r"40\s*%|over 40"], [r"500"]],
    "palm-08": [[r"3072|3,072"], [r"768"], [r"two|\b2\b"]],
}
for q in Q:
    q["key_facts"] = KEYFACTS.get(q["id"], [])
    assert q["is_answerable"] == bool(q["key_facts"]), q["id"]

out = Path(__file__).resolve().parent / "questions.jsonl"
out.write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in Q) + "\n", encoding="utf-8")
print(len(Q), "questions ->", out)
