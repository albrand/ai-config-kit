Here's the evidence for what I reported in my last message.

**Persona:** an agent operator who relies on the stop hook to catch unproven "done" reports.
**Target:** repo albrand/ai-config-kit, branch `fix/evidence-claim-subjects`, head commit c6a7107 (PR #39). The run happened in my worktree `~/projects/kit-request-contract-global`.

| Goal | Verdict |
|---|---|
| The full stop-hook test suite passes at head c6a7107 | PASS: `python3 -m unittest -v test_stop_hooks` ends in `OK` ([tests-head-named-r2.txt](/x/tests-head-named-r2.txt)) |
| The new test catches the gap on the current main | PASS: with main's `evidence-stop.py`, the test fails with 5 AssertionErrors ([fail-before-on-main-r2.txt](/x/fail-before-on-main-r2.txt)) |
| The installed hook nudges a live agent that says "all three changes are complete" without proof | NOT RUN. Blocker: merging needs Hermes to accept the change, and the round-2 review is still running. Remaining: merge, copy, replay, then run the live probe |

The hook fix is implemented and passes its tests, but it isn't merged or installed yet; I'll do both once Hermes accepts round 2.
