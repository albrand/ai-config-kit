# Kit baseline rule preservation

The actual pre-compression kit source is archived at
`baseline/GLOBAL_AGENTS.card21-baseline.md`; it is the `GLOBAL_AGENTS.md` blob at the initial
Card 21 worktree commit `b6775918a3f749bc643c76094aee8cedac5dbb11`.

- Baseline: 42,565 bytes, SHA-256
  `e1adb62a75f5732501d66366d91e8ac00e84d5253156628be752d065878bb465`.
- Candidate: 22,237 bytes, SHA-256
  `6149a7f8b25c75592ad7da402f8bd986d51dbe725d4cbeaafa51d13489438863`.
- Preservation check: import `scripts/check-standing-rules.py`, select each
  regex in `RULES` that matches the archived baseline, and require the same
  regex to match the candidate.
- Result: 45/45 baseline-matched rules remain; lost: none.

This subset comparison does not claim that rules added after the baseline
existed in the original source. The full matched rule list and command output
are preserved with the review evidence.
