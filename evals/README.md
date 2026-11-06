# Evals: how well does the RAG work?

Scripts that score the real system on your real data: the same search and chat code the public site
runs, against Supabase and Gemini. Run them from the repo root whenever you want a score, for example after
publishing a video, changing a setting, or when Google updates the Gemini model. They are not part of the
normal tests (they use the network and take a few minutes).

| Step | Command | Cost | What it tells you |
|---|---|---|---|
| 0. Questions (once) | `.venv\Scripts\python evals\make_questions.py` | a few Claude calls | Writes `data/questions.json`: one question per narration window of each published video (so we know where the answer is), questions the video doesn't answer, and questions for 20 research passages per project. Run again to add new videos; `--refresh` rewrites all. |
| 1. Retrieval | `.venv\Scripts\python evals\retrieval.py` | free (embeddings) | Does search find the passage that holds the answer? hit@1/3/6 and MRR for narration and research sources, hybrid vs vector-only; is the right video first in the search bar; do off-topic searches return nothing. |
| 2. Answers | `.venv\Scripts\python evals\answers.py` | ~30 Gemini answers (free tier) + a few Claude calls | Asks the chatbot real questions. Code checks every [m:ss] points to a real passage and to the right one; Claude grades grounded / correct / "says so when the video doesn't cover it". |
| 3. Guard rails | `.venv\Scripts\python evals\guardrails.py` (`--no-model` = free) | embeddings + Gemini only for attacks that pass the check | Off-topic, jailbreak and harmful questions (`data/attacks.json`) vs real ones: how many get past the free relevance check, whether the model then declines, how many real questions are wrongly turned away, and what other cutoffs would do. |
| Speed and tokens | `.venv\Scripts\python evals\speed.py` (`--research-only`, `--rag-first`, `--topic "..."`) | one research + one script each way on your Claude plan, ~15-25 min | Research and script writing the old way (Claude searches the web) vs RAG, on the same topic and settings: time, Claude calls, tool turns (each web search or page read is one), input/output tokens and the API-equivalent cost the Claude CLI reports. Also re-research with sources already stored. Nothing is saved to your projects. |

Reports go to `evals/reports/` (not committed): a Markdown summary and the raw results per run, and one line
per run in `history.jsonl` so you can compare runs over time.

Notes
- Claude runs through the studio's provider (the Claude Code CLI on your Pro plan by default).
- Scores are only comparable between runs on the same question set. Add attacks to `data/attacks.json`
  freely, but expect the numbers to move.
- The scoring helpers have unit tests: `.venv\Scripts\python -m pytest -q evals/tests`.
