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
  to `bb`, or `"$BB_CLI"`, with `--prompt-file`, `--message-file`, `$(cat f)`,
  `< f` and heredocs read), plus `fleet_member_spawn`, `fleet_member_tell` and
  `fleet_delegate`.
- Only an invocation counts: the command is split into simple commands
  (`scripts/shell_dispatch.py`), and `bb` must be the command word (after
  `;` `&&` `||` `|`, inside `$(...)` or backticks, after `env`, `command`,
  `exec`, assignments, or inside `sh -c '...'` / `eval`), or an unquoted word
  after a wrapper that runs it (`timeout`, `xargs`, `nice`, `sudo`,
  `find -exec`). The same words in a quoted argument (`printf`, `echo`,
  `grep`, `git commit -m`), a comment or a heredoc written to a file are data
  and pass.
- Every such dispatch must carry one of (each dispatch its own; a `serves:`
  in a sibling command does not cover it):
  - `serves: P<n>`, where P<n> is an **open** purpose;
  - `serves: revision "<quote>"`, where the quote equals an accepted
    revision's quote (whitespace collapsed, never a substring).
- A denial lists the open purposes in the user's words.
- A ledger that exists but can't be read denies dispatches (fails closed).
- Every decision is appended to `~/.local/state/agent-quality/scope-decisions.jsonl`.
- It decides by 12 s after the chain started (`HOOK_T0`, exported by
  `coordinator-hook-pretool.sh`), because a hook the host times out (15 s)
  lets the command run. At the deadline, or when an earlier stage used the
  time up, it decides on shape alone: with a ledger, a dispatch-shaped call
  (`fleet_member_spawn|tell`, `fleet_delegate`, `thread … spawn|create|tell|message`)
  without `serves: P<n>` or `serves: revision` denies; anything else passes.

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

When a child is finished, release it, so its archive stays archived:

    scope-gate.py release <coordinator> <child> --evidence "<why it is done>"

The release is recorded in the coordinator's ledger (`released_children`,
with the evidence and when). The hold, the orphan scan and the archive guard
then skip that child, and only that child; the audit line names the release.
Record it on the child's parent ledger: a release in any other ledger holds
nothing back. A child with its own ledger and unfinished purposes is still
held by that ledger. A circuit successor's releases survive the hand-back.

Every archive is appended to `~/.local/state/agent-quality/archive-audit.jsonl`.

## Circuit successor (fleet plugin)

When the fleet circuit hands a thread to a successor, the successor gets a
copy of the origin's ledger: the same purposes and revisions, plus
`inherited_from` and `inherited_at`. Its dispatches are gated the same way.
At hand-back, status changes the successor made (newer `status_marked_at`),
its evidence, new purposes and new revisions merge into the origin's ledger,
and the successor's file is kept as `<successor>.json.returned-<ms>`.

## Known limits

- opencode has no PreToolUse hook, so dispatches from opencode threads (GLM)
  are not gated. Only Claude Code and Codex run the gate.
- Kit branch `feat/qa-gate-v3` (e82faa9): its `install.sh` would overwrite the
  scope pretool hook in `~/.agent-hooks` (`coordinator-hook-pretool.sh`). Re-run
  `hooks/install-scope-gate.sh` after installing from that branch.
- The deadline covers the ship gate and the scope gate. The chain's last
  stage, `coordinator-hook.sh pretool` (coordinator-mode edit blocks), has
  none of its own and gets what is left of the 15 s.
- At the deadline the scope gate decides by shape over the whole payload, so
  from a ledger thread a Write or Edit whose text reads like
  `thread … tell` without `serves:` is denied too (Codex runs the chain for
  every tool). It fails closed.
- Not parsed:

 a script run from a file (`sh dispatch.sh`), a script piped into

  a shell (`cat x | sh`), a command handed to a wrapper as one quoted string
  (`watch 'bb thread tell ...'`, `ssh host 'bb ...'`), and `bb` reached
  through an alias, a function or a variable other than `BB_CLI`.


## Tests


`python3 scripts/scope-gate.py selftest` runs Claude and Codex payload shapes,
including every shell case in `tests/fixtures/dispatch-cases.json`,
against `tests/fixtures/scope-ledger.json`. The fleet plugin's
`test/scope-guard.test.mts` uses the same fixture.
