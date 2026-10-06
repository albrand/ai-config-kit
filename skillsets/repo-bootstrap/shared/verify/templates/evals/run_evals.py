#!/usr/bin/env python3
"""Run an eval set against the real LLM feature, k times per case, and score it with verify.py.

  run_evals.py live   --cmd "node scripts/triage.js" [--k 3] [--dataset evals/dataset.jsonl]
  run_evals.py record --cmd "..." [--k 3]          live, and keep the predictions for replay
  run_evals.py replay                              score the kept predictions (no model calls)

--cmd gets one dataset row as JSON on stdin and prints its answer on stdout: either plain text
(the output) or a JSON object {"output": ..., "judge": true|false}. Rows look like
{"id": "c1", "input": {...}, "expected": "urgent", "human": true}; see dataset.example.jsonl.
Scoring and thresholds are verify.py eval-score's (pass@1, pass^k, per-label recall, judge TPR/TNR).
Standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VERIFY = os.environ.get("VERIFY_PY", str(Path.home() / ".agents/skills/verify/scripts/verify.py"))


def load(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def predict(cmd, row, timeout):
    p = subprocess.run(cmd, shell=True, input=json.dumps(row), capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        return {"id": row["id"], "output": None, "error": (p.stderr or p.stdout)[-500:]}
    text = p.stdout.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "output" in obj:
            return {"id": row["id"], **obj}
    except ValueError:
        pass
    return {"id": row["id"], "output": text}


def score(dataset, predictions, thresholds):
    args = [sys.executable, VERIFY, "eval-score", "--dataset", dataset, "--predictions", predictions]
    if Path(thresholds).exists():
        args += ["--thresholds", thresholds]
    return subprocess.run(args).returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "record", "replay"])
    ap.add_argument("--cmd")
    ap.add_argument("--k", type=int, default=3, help="samples per case; pass^k needs k >= 2")
    ap.add_argument("--dataset", default="evals/dataset.jsonl")
    ap.add_argument("--thresholds", default="evals/thresholds.json")
    ap.add_argument("--recorded", default="evals/recorded.jsonl")
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()
    if a.mode == "replay":
        if not Path(a.recorded).exists():
            print(f"no recorded predictions at {a.recorded}; run `record` first", file=sys.stderr)
            return 2
        return score(a.dataset, a.recorded, a.thresholds)
    if not a.cmd:
        ap.error("--cmd is required for live and record")
    rows = load(a.dataset)
    preds = [predict(a.cmd, row, a.timeout) for row in rows for _ in range(a.k)]
    errors = [p for p in preds if p.get("error")]
    for p in errors[:5]:
        print(f"case {p['id']} failed to run: {p['error']}", file=sys.stderr)
    out = Path(a.recorded) if a.mode == "record" else Path(tempfile.mkstemp(suffix=".jsonl")[1])
    out.write_text("".join(json.dumps(p) + "\n" for p in preds))
    print(f"{len(rows)} cases x {a.k} samples, {len(errors)} errors -> {out}")
    return score(a.dataset, str(out), a.thresholds) or (1 if errors else 0)


if __name__ == "__main__":
    sys.exit(main())
