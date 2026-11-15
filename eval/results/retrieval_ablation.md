| Configuration | Hit@k | Recall@k | All evidence | MRR | Gold page hit | Follow-up hit | Context tokens | Retrieval p50 ms |
|---|---|---|---|---|---|---|---|---|
| A. Original design (10k-char chunks, dense, k=4) | 0.714 | 0.648 | 0.571 | 0.488 | 0.829 | 0.80 | 9,454 | 31.3 |
| B. Token chunks (512 tok, sentence-aligned, dense, k=5) | 0.714 | 0.635 | 0.543 | 0.553 | 0.771 | 0.60 | 2,384 | 28.1 |
| C. + contextual headers | 0.829 | 0.764 | 0.686 | 0.587 | 0.886 | 0.80 | 2,401 | 28.9 |
| D. BM25 keyword only | 0.886 | 0.754 | 0.629 | 0.639 | 0.914 | 0.60 | 2,418 | 1.1 |
| E. Hybrid dense+BM25 (RRF) | 0.886 | 0.778 | 0.657 | 0.652 | 0.971 | 0.60 | 2,410 | 35.0 |
| F. + cross-encoder reranker | 0.914 | 0.835 | 0.743 | 0.754 | 0.971 | 0.60 | 2,408 | 372.9 |
| G. + history-aware follow-ups (= UPGRADED default) | 0.943 | 0.864 | 0.771 | 0.780 | 0.971 | 0.80 | 2,409 | 378.2 |
| sweep: chunk 192 tok | 0.829 | 0.670 | 0.514 | 0.645 | 0.943 | 0.80 | 837 | 199.7 |
| sweep: chunk 320 tok | 0.886 | 0.765 | 0.657 | 0.688 | 0.943 | 0.80 | 1,474 | 304.7 |
| sweep: final k=3 | 0.857 | 0.735 | 0.600 | 0.762 | 0.857 | 0.60 | 1,451 | 379.9 |
| sweep: final k=8 | 1.000 | 0.935 | 0.857 | 0.788 | 1.000 | 1.00 | 3,865 | 372.2 |
| sweep: dense + rerank (no BM25) | 0.943 | 0.835 | 0.714 | 0.724 | 0.971 | 0.80 | 2,408 | 377.7 |
| sweep: embedder bge-base (110M, 3x larger) | 0.943 | 0.864 | 0.771 | 0.780 | 0.971 | 0.80 | 2,412 | 376.2 |
| sweep: embedder all-MiniLM-L6-v2 | 0.943 | 0.864 | 0.771 | 0.780 | 0.971 | 0.80 | 2,404 | 361.7 |
