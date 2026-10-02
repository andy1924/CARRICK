# Synthetic matching check — 2026-10-02

Eight authored notes in `data/samples/matching-eval.jsonl` were compared against the twelve-activity synthetic pump station schedule. The command was `.venv/bin/python -m scripts.evaluate_matching --ai`, with OpenAI structured extraction, `text-embedding-3-small` retrieval, and the local `cross-encoder/ms-marco-MiniLM-L6-v2` reranker.

| Measure | Rule baseline | AI path |
| --- | ---: | ---: |
| Correct activity ranked first | 7 / 8 | 8 / 8 |
| Correct activity in top three | 8 / 8 | 8 / 8 |
| Correct event kind | 2 / 8 | 5 / 8 |
| Processing errors | 0 | 0 |

The AI path corrected the colloquial “pressure checked the northern water line” case, which the lexical baseline linked to a weld activity instead of the hydrotest. Both paths still missed event kinds in some phrasing. These are development fixtures authored alongside the product, not independent field reports. They establish that the path runs end to end and show one improvement; they do not establish production accuracy, calibration, or robustness. A reviewed held-out set and real project terminology remain the next gate.
