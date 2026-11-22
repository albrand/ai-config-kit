# Evals

An LLM feature gives a different answer each time, so one passing run proves little. An eval set
runs the real feature on labelled cases several times and measures how often it is right.

1. Copy `run_evals.py`, `dataset.example.jsonl` (as `evals/dataset.jsonl`) and
   `thresholds.example.json` (as `evals/thresholds.json`) into the repo.
2. Build the dataset from real traffic: cases users actually sent, the ones that went wrong, and
   the rare ones that matter most (for triage: every kind of emergency). Label `expected` by hand.
   Mask personal data before a case enters the repo; the owner decides what masking is enough.
3. Write a small entry point for `--cmd` that reads one row on stdin, calls the feature exactly as
   production does (same prompt, model, temperature, tools), and prints the answer.
4. Set thresholds from what users need, not from today's score. Recall on the label that hurts
   most when missed (for example `urgent`) gets its own threshold.

What the numbers mean:

- `pass_at_1`: share of all samples that were right.
- `pass_all_k`: share of cases right in every sample, the consistency a user meets day to day.
- per-label precision and recall: which kind of answer it gets wrong.
- judge TPR/TNR: when an LLM grades free text (`judge` in the prediction), how often it agrees
  with the human label (`human` in the dataset). Trust a judge only above `judge_min`.

verify config:

```json
"evals": {
  "run": "python3 evals/run_evals.py live --cmd 'node scripts/eval-entry.js' --k 3",
  "env": ["OPENAI_API_KEY"],
  "paths": ["src/prompts/**", "src/llm/**", "evals/**"],
  "timeout": 1800
}
```

`record` keeps the predictions in `evals/recorded.jsonl`; `replay` re-scores them with no model
calls, which is useful for checking the scoring and post-processing code on every change while
live runs are limited to changes under `paths`.
