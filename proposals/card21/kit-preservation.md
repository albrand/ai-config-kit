# Kit baseline rule preservation

The actual pre-compression kit source is archived at
`baseline/GLOBAL_AGENTS.card21-baseline.md`; it is the `GLOBAL_AGENTS.md` blob at the initial
Card 21 worktree commit `b6775918a3f749bc643c76094aee8cedac5dbb11`.

- Baseline: 42,565 bytes, SHA-256
  `e1adb62a75f5732501d66366d91e8ac00e84d5253156628be752d065878bb465`.
- Candidate: 20,110 bytes, SHA-256
  `27c98adfebee8c1101f67062ebc66c23a3ccc429a43282b417cd5e80ec7133bf`.
- Preservation check: import `scripts/check-standing-rules.py`, select each
  regex in `RULES` that matches the archived baseline, and require the same
  regex to match the candidate.
- Result: 42/42 baseline-matched rules remain; lost: none.

This subset comparison does not claim that rules added after the baseline
existed in the original source. The full matched rule list and command output
are preserved with the review evidence.
