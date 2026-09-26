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
- Dispatches it gates: every `bb` verb that hands a thread text, derived
  from the help of every core and plugin command group (nested groups
  included): `thread spawn|create|fork|tell|message|edit-message`, `thread
  queue create|update|send`, `thread interactions respond` and `thread
  interactions answer --text`, `fleet group-create|task-add|advise` and
  `fleet member-add --concern`, `instructions set` (custom instructions go
  into every agent), and `automation create|update` with `--prompt` (the
  prompt an agent runs when the automation is due; `--target-thread`
  re-prompts an existing thread), `--script` or `--script-file`. An
  automation's script is scanned like a command: each dispatch in it needs
  its own serves line. A `--script-file` is read like a brief file; with
  `--host` (the file is on another machine) or when it cannot be read, the
  call denies unless the command's own words serve. A node or python3 script
  is not parsed: one that reads like a dispatch needs the serves line in its
  text. Inside a script, a relative brief path or a variable in one denies
  (the script runs later, from a directory and environment the hook cannot
  know). `automation run|resume`, and an `update` that retargets or
  reschedules (`--target-thread`, `--cron`, `--at`, `--in`) without new text,
  fire the text the automation already stores: the gate reads it with `bb
  automation show <id> --json` and applies the same rule, and denies when it
  cannot be read. An answer that only picks offered choices (`--choice`), a
  member-add without a concern, and an automation update of other fields
  carry no new text and pass.
  Agent tools (`scripts/scope-gate.py` `MCP_FIELDS`, with the fields read):
  `fleet_member_spawn` (prompt, concern), `fleet_member_tell` (message),
  `fleet_delegate` (task, context), `fleet_task_create` (title, body),
  `fleet_task_update` (title, body, blocked reason; gated only when it sets
  one of those or an assignee: a task handed to a member carries its brief,
  and members and the orchestrator read a blocked reason as work), `fleet_advise`
  (question, context), `fleet_context_set` (key, content: entries go into
  every member's instructions) and `bb_workflow_run` (script, source, args,
  and the `scriptPath` file). Claude reaches them through the PreToolUse
  matcher the installer writes; Codex runs the chain for every tool. The
  selftest walks bb's help and fails on a text-carrying verb the gate does
  not cover (`fleet validate|review|hermes` are exempt: a claim to the
  reviewer, not a brief; `terminal send` types into a shell session;
  `notify send` is a desktop notice to the person; `voice transcribe` takes
  a transcription hint), and reads every enabled plugin's source, at any
  depth, and fails on a registered agent tool that is neither gated nor in
  `MCP_EXEMPT` with its reason (read-only tools, `fleet_review`,
  `fleet_curate`, `fleet_optimization`, `fleet_member_retire`,
  `bb_workflow_result`, `AskUserQuestion`, the `browser_*` and `mcp_*`
  tools), or whose name it cannot read (a name held in a variable is
  resolved from the same file). `bb` is matched in any case (`BB`: the filesystem is
  case-insensitive), as a path, as `"$BB_CLI"` or `"${BB_CLI:-bb}"`, and a
  command word only known at run time (`$(...)`, `$VAR`) followed by a
  dispatch verb counts too. ANSI-C quoting (`$'tell'`, `$'\x74ell'`) is
  decoded first. Only a bare help request (`bb thread tell --help`, nothing
  else after the verb) passes: a `-h` anywhere else can be an option's value
  (`--title -h`) or a positional after `--`, and the dispatch runs.
- Brief files are read: `--prompt-file`, `--message-file`, `$(cat f)`, `< f`
  and heredocs. `~`, `$VAR`, `${VAR}` and `${VAR:-default}` in the path are
  expanded from the hook's environment (the host gives the hook and the
  command the same one), so `--message-file $TMPDIR/brief.md` works. An unset
  variable denies. So does a variable the command sets itself (`D=...;`,
  `export D=`, `for D in`, `read D`), even one the hook's environment also
  has: the hook reads the file before the command runs, so it would read
  another file. Name the brief file by a literal path (the deny says so). A
  file the same command writes does not exist yet when the hook runs: write
  the brief file in a separate step (the deny says so). Only a regular file
  is read: a FIFO, a device or a directory denies at once (opening a FIFO
  waited for a writer, which is the command itself). A relative path in a
  command that changes directory (`cd d && ... --message-file brief.md`)
  denies: the hook reads it before the command runs, from a directory it
  cannot know; use an absolute path (the deny says so).
- Only an invocation counts: the command is split into simple commands
  (`scripts/shell_dispatch.py`), and `bb` must be the command word (after
  `;` `&&` `||` `|`, inside `$(...)` or backticks, after `env`, `command`,
  `exec`, assignments, `env -S '...'`, inside `sh -c '...'` / `eval`, a
  here-string, heredoc or process substitution a shell reads
  (`bash <<< '...'`, `bash <(echo ...)`, `source <(...)`)), or an unquoted
  word after a wrapper that runs it (`timeout`, `nice`, `sudo`,
  `find -exec`), or `xargs [opts] bb` (its verb comes from stdin, so any
  `xargs bb` counts as a dispatch). The same words in a quoted argument (`printf`, `echo`,
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
- A hook the host times out (15 s) lets the command run, so the decision is
  made before that in two layers. `coordinator-hook-pretool.sh` stamps
  `HOOK_T0` and runs each gate stage under a supervisor that kills the stage's
  whole process group 11 s after `HOOK_T0` and then decides by shape in shell,
  without Python (review r1 measured 2-3.5 s of shell and interpreter start at
  load 160-213); a stage reached after 11 s is not started. Inside the stage
  the Python gate keeps its own deadline at 10 s (`HOOK_HARD_S`). The shape
  decision reads only the call's own words: a gated agent tool's text
  fields, or the command; never the tool call's description or a comment,
  and no brief file. Each dispatch serves on its own, as in the normal
  decision: the command is split at every `;` `&` `|` `(` `)` and newline,
  quoted or not (more stretches than the shell makes, so a serves line can
  only be cut off from its dispatch, never lent to another), and every
  stretch that is dispatch-shaped (a command matching `thread … spawn|create|
  fork|tell|message|edit-message|queue|interactions … answer|respond`, `fleet
  group-create|task-add|advise|member-add`, `automation create|update|run|
  resume` or `instructions set`, any case, quotes and backslashes removed; or
  one holding an ANSI-C escape) must name an **open** purpose (`serves:
  P<n>`; a blocked or unknown id does not count) or an accepted revision
  (its quote, or its part before a separator if that is 20 characters or
  more). A stretch that runs a nested script (`sh -c`, `eval`, `--script`,
  `<<<`, `env -S`, `node -e`) never serves at the deadline. A gated agent
  tool is one stretch. In shell it is one `jq` run over the payload and the
  ledger, made before the stages start (so the path after a kill starts no
  process); no `jq` denies any dispatch word or ANSI-C escape. The same shape block is in
  `scope-gate-hook.sh`, which falls back to it when Python cannot run;
  `hooks/test-hook-chain.sh` checks the copies match and that the `jq` shape
  and `scope-gate.py shape` agree on `tests/fixtures/shape-cases.json`.

If the work serves no open purpose, it is outside the request. Ask the user.
When they approve, record their approval with `revise`, then quote it in
`serves:`.

## The idle guard (fleet plugin service `fleet-scope-guard`)

Every 10 min it checks each ledger with an open purpose. When the thread has
been idle for 30 min or more, has no active child, no queued message and no
background task, and isn't relieved by a circuit successor, it gets one nudge.
The nudge lists the open purposes and says: dispatch the next step, or mark
the purpose blocked-on-user with the exact ask.

- It makes at most one nudge attempt per hour. A failed send counts (it may
  still have been delivered), and each failure in a row adds 10, 20, 40, then
  60 min to the wait.
- A coordinator a person archived (`archived_by_user_at` in its ledger) is
  not nudged until it works again after that archive.
- blocked-on-user and done purposes don't trigger nudges.
- Each nudge is a coordinator-idle episode in `bb fleet value`.
- `bb fleet scope` shows every ledger and what the guard would do now.

## Archive hold (fleet plugin)

The following threads are never archived by fleet (orphan scan,
`orphans --retire`, member retire, orchestrator passes):

- A thread whose own or parent's ledger has an unfinished purpose.
- A review thread under a topic.

If anything else archives one, fleet restores it once and tells the
coordinator, including when the restore fails:

- The coordinator itself is never restored. A person archiving it means it:
  its ledger gets `archived_by_user_at`, and the idle guard leaves it alone.
- A child is restored at most once (`archive_restores` in the coordinator's
  ledger). Archived again after that, the archive stands; the ledger records
  `archived_again_at` and the coordinator is told.

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
and the successor's file is kept as `<successor>.json.returned-<ms>`. When
both added a different purpose under the same id, both are kept: the
successor's is renumbered past every id and carries `renumbered_from`.


## Known limits

- opencode has no PreToolUse hook, so dispatches from opencode threads (GLM)
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
