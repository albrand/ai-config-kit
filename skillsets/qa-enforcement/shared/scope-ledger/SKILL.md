---
name: scope-ledger
description: Keep a coordinator on what the user asked for. A per-thread ledger of the user's purposes (verbatim), a PreToolUse gate that denies spawns and tells that do not say which open purpose they serve, and the fleet idle guard that nudges a coordinator sitting idle with open purposes. Use when coordinating children, when the gate denies a dispatch, or when the fleet scope guard nudges you.
---

# scope-ledger

Operator complaint (2026-09-25): "agents are deviating and drifting from the
original focus and there is nothing enforcing this scope". A coordinator also
sat idle ~15 h with open work. This skill is the enforcement: a ledger, a gate
and a guard. They run whenever a ledger exists. There is no off switch other
than finishing the purposes.

## The ledger

`~/.local/state/agent-quality/scope/<thread_id>.json`, one per coordinator
thread:

- `purposes`: `{id: "P1", text, done_when, status, evidence, status_marked_at, ask}`.
  - `text` is the user's own words, verbatim.
  - `status` is `open`, `done` or `blocked-on-user`.
- `accepted_revisions`: `{quote, accepted_at, source}`. Each entry is a scope
  change the user approved, quoted verbatim.

```sh
G=~/.claude/skills/scope-ledger/scripts/scope-gate.py
python3 $G init <thread> --from ledger.json        # refuses to overwrite
python3 $G add <thread> --text "<user's words>" --done-when "<observable end state>"
python3 $G mark <thread> P2 blocked-on-user --ask "<the exact question for the user>"
python3 $G mark <thread> P1 done --evidence "<commit / URL / measurement>"
python3 $G revise <thread> --quote "<the user's approval, verbatim>" --source <ref>
python3 $G show <thread>
python3 $G check <thread> "<brief text>"           # the gate's decision, no tool call
```

## The gate (PreToolUse, Claude Code and Codex)

`~/.agent-hooks/scope-gate-hook.sh` is chained in `coordinator-hook-pretool.sh`
after the QA ship gate.

- It only acts when `$BB_THREAD_ID` has a ledger.
- Dispatches it gates: `bb thread spawn|create|tell|message` (bare `bb`, a path
  to `bb`, or `"$BB_CLI"`, with `--prompt-file`, `--message-file`, `$(cat f)`
  and `< f` read), plus `fleet_member_spawn`, `fleet_member_tell` and
  `fleet_delegate`.
- Every such dispatch must carry one of:
  - `serves: P<n>`, where P<n> is an **open** purpose;
  - `serves: revision "<quote>"`, where the quote equals an accepted
    revision's quote (whitespace collapsed, never a substring).
- A denial lists the open purposes in the user's words.
- A ledger that exists but can't be read denies dispatches (fails closed).
- Every decision is appended to `~/.local/state/agent-quality/scope-decisions.jsonl`.

If the work serves no open purpose, it is outside the request. Ask the user.
When they approve, record their approval with `revise`, then quote it in
`serves:`.

## The idle guard (fleet plugin service `fleet-scope-guard`)

Every 10 min it checks each ledger with an open purpose. When the thread has
been idle for 30 min or more, has no active child, no queued message and no
background task, and isn't relieved by a circuit successor, it gets one nudge.
The nudge lists the open purposes and says: dispatch the next step, or mark
the purpose blocked-on-user with the exact ask.

- It sends at most one nudge per hour.
- blocked-on-user and done purposes don't trigger nudges.
- Each nudge is a coordinator-idle episode in `bb fleet value`.
- `bb fleet scope` shows every ledger and what the guard would do now.

## Archive hold (fleet plugin)

The following threads are never archived by fleet (orphan scan,
`orphans --retire`, member retire, orchestrator passes):

- A thread whose own or parent's ledger has an unfinished purpose.
- A review thread under a topic.

Fleet restores them if anything else archives them, and tells the coordinator.
Every archive is appended to `~/.local/state/agent-quality/archive-audit.jsonl`.

## Tests

`python3 scripts/scope-gate.py selftest` runs Claude and Codex payload shapes
against `tests/fixtures/scope-ledger.json`. The fleet plugin's
`test/scope-guard.test.mts` uses the same fixture.
