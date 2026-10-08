# PreToolUse dispatch-gate procedure

## The gate (PreToolUse, Claude Code and Codex)

`~/.agent-hooks/scope-gate-hook.sh` is chained in `coordinator-hook-pretool.sh`
after the QA ship gate.

- It only acts when `$BB_THREAD_ID` has a ledger.
- Dispatches it gates: every `bb` verb that hands a thread text, derived
  from the help of every core and plugin command group (nested groups
  included): `thread spawn|create|fork|tell|message|edit-message`, `thread
  queue create|update|send`, `thread draft set` when given a message,
  `thread interactions respond` and `thread interactions answer --text`,
  `fleet group-create|task-add|advise` and
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
  know). `automation run|resume`, and an `update` that retargets,
  reschedules or re-environments it (`--target-thread`, `--cron`, `--at`,
  `--in`, `--env-json`) without new text,
  fire the text the automation already stores: the gate reads it with `bb
  automation show <id> --json` and applies the same rule, and denies when it
  cannot be read. `bb plugin run <plugin> ...` counts as that plugin's
  command, and `bb plugin config custom-instructions set ...` (the custom
  instructions are that plugin's setting) as `instructions set`.
  `bb plugin rpc call <plugin> <method>` is a dispatch unless that exact
  (plugin id, method) pair is in `RPC_EXEMPT` (`shell_dispatch.py`) as a
  handler whose implementation was read and hands no text to a thread. No
  namespace is exempt, and an exempt method name served by another plugin is
  not, so a handler bb adds later is gated until someone reads it. A call
  with any word built at run time is a dispatch too. The selftest fails on a
  discoverable method (`bb plugin rpc list`) that is neither exempt nor gated. The serves line of `instructions set` is part of the
  text every agent then receives, as with `fleet_context_set`. An answer
  that only picks offered choices (`--choice`), a
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
  dispatch verb counts too. A command, group or verb word a substitution is
  glued into (`bb automation$(echo) run a1`, `bb th`x`read tell`,
  `bb automation${X} run`), or a substitution, parameter expansion or
  variable as its own word in the verb zone (`bb thread $(echo) tell`,
  `bb thread $V tell`, `bb $(echo) thread tell`), is dispatch-shaped the
  same way: what runs is unknown, so it needs its serves line (review r2d
  and its follow-up). ANSI-C quoting
  (`$'tell'`, `$'\x74ell'`) is
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
