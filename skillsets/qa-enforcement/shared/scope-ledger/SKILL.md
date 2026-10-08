---
name: scope-ledger
verify: python3 scripts/scope-gate.py selftest
verified: 2026-10-01
description: Keep a coordinator on what the user asked for. A per-thread ledger of the user's purposes (verbatim), a PreToolUse gate that denies spawns and tells that do not say which open purpose they serve, a Stop check that blocks an early stop while open purposes have nothing running, and the fleet idle guard that nudges a coordinator sitting idle with open purposes. Use when coordinating children, when the gate denies a dispatch, or when the fleet scope guard or the scope-closeout check nudges you.
---

# scope-ledger

Operator complaint (2026-09-25): "agents are deviating and drifting from the
original focus and there is nothing enforcing this scope". A coordinator also
sat idle ~15 h with open work. This skill is the enforcement: a ledger, a gate
and a guard. They run whenever a ledger exists. There is no off switch other
than finishing the purposes.

## Rules and invariants

- The ledger and its enforcement run whenever a ledger exists; there is no off switch other than finishing the purposes.
- Keep user purpose text verbatim and accepted revisions as verbatim approved quotes. A request contract is a review step, never a gate.
- A dispatch must serve an open purpose or exact accepted revision. The gate fails closed when a ledger or brief cannot be read; dispatches cannot borrow a sibling command's serves line.
- The idle guard nudges an idle coordinator with open work. The Stop check blocks once when open purposes have nothing carrying them; a status report is not completion.
- Fleet archive holds protect threads with unfinished purposes and review threads. Release only a finished child with evidence in its parent's ledger.
- The gate's deadline behavior and documented parser limits are part of the contract; retain the `Known limits` section here because `shell_dispatch.py` points to it.

## Steps

1. Initialize and maintain the ledger. Read `references/ledger-and-contract.md` when you reach this step.
2. Decide whether a dispatch carries text and must serve an open purpose or accepted revision. Read `references/dispatch-gate.md` when you reach this step.
3. Respond to idle nudges and closeout checks by continuing, completing, or recording the exact user-owned blocker. Read `references/idle-and-closeout.md` when you reach this step.
4. Hand back circuit successors and release finished children with evidence. Read `references/fleet-lifecycle.md` when you reach this step.

## Known limits

- opencode has no PreToolUse hook, so dispatches from opencode threads
  are not gated. Only Claude Code and Codex run the gate.
- Kit branch `feat/qa-gate-v3` (e82faa9): its `install.sh` would overwrite the
  scope pretool hook in `~/.agent-hooks` (`coordinator-hook-pretool.sh`). Re-run
  `hooks/install-scope-gate.sh` after installing from that branch.
- The chain's last stage, `coordinator-hook.sh pretool` (coordinator-mode
  edit blocks), is cut at 12.5 s after `HOOK_T0` and then passes, as a host
  timeout would, but inside the 15 s.
- At the deadline (only when the gate could not finish), these deny even
  though the normal decision would allow them; each fails closed and a retry
  gets the normal decision: a command whose words read like a dispatch
  (`echo "bb thread tell ..."`, a comment that mentions one); a serves line
  after a separator inside the brief (`"fix it; serves: P1"`) or in a heredoc
  body (both are another stretch); a dispatch inside `sh -c`, `eval` or an
  automation `--script`; any stretch with an ANSI-C escape (`IFS=$'\n'`); a
  revision whose quote splits at a separator less than 20 characters in;
  and `automation run|resume` (the stored text is not read then).
- An automation that already exists fires on its own schedule without the
  gate: only a ledger thread's create, update, run and resume are checked.
- `automation run|resume` and a retarget or reschedule read the stored
  prompt or script through `bb automation show` (a local server call, well
  inside the deadline); when bb cannot answer, the call is denied.
- A brief file written in the same command as the dispatch
  (`printf ... > f && bb thread tell x --message-file f`) is not there when
  the hook reads it, so the dispatch is denied (fails closed).
- At the shell deadline a brief file is not read: a dispatch whose `serves:`
  is only in a file is denied and has to be retried.
- `python3 -c '...'` (or any interpreter) that runs `bb` through its own
  process API is not parsed. An automation's node or python3 script is not
  parsed either: it is gated only when its text reads like a dispatch.
- TOCTOU: the hook reads a brief file before the command runs, so a brief
  overwritten, copied over, re-linked or edited in place between the two
  (`cp`, `ln -sf`, `sed -i`) is sent unread. It needs the same user as the
  agent; there is no permission gap, only the time between the reads.
- `eval "$(...)"` and `sh -c "$(...)"`: the script is only known when the
  substitution runs, so a dispatch it builds is not seen.
- `bb` under another name (a copy or symlink named otherwise) and a git
  alias that runs `bb` (`git config alias.t '!bb thread tell'`) are not
  parsed.
- A saved workflow run by name (`bb_workflow_run` with `name`) is not read;
  it needs the serves line in `args`, or the script passed inline.
- Not parsed:

 a script run from a file (`sh dispatch.sh`), a script piped into

  a shell (`cat x | sh`), a command handed to a wrapper as one quoted string
  (`watch 'bb thread tell ...'`, `ssh host 'bb ...'`), and `bb` reached
  through an alias or a function.

## Tests


`python3 scripts/scope-gate.py selftest` runs Claude and Codex payload shapes,
including every shell case in `tests/fixtures/dispatch-cases.json`,
against `tests/fixtures/scope-ledger.json`. The fleet plugin's
`test/scope-guard.test.mts` uses the same fixture.
`hooks/tests/test_closeout_stop.py` covers the closeout check alone and in
the stop chain.
