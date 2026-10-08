# Idle-guard and Stop closeout procedures

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
## The closeout check (Stop, Claude Code and Codex)

Operator complaint (2026-09-30), after a strict replay of false-done cases:
the main real failure was coordinators stopping early with a status report,
"remains blocked" or an offer to continue while authorized work was left. The
user corrected each one well before the idle guard's 30 minutes; 5 of the 6
cases were Codex. `scripts/closeout-stop.py` runs the idle guard's predicate
when the turn ends. `~/.agent-hooks/qa-stop-hook.sh` computes it alongside
the evidence check and returns both reasons in one bounded nudge. A formatting
correction must not hide unfinished work.

- It blocks the stop once when the thread's ledger has an open purpose and
  nothing carries it.
  - A queued message carries every purpose: it is the next input and resumes
    this thread, which runs the check again.
  - An active or pending child carries only the purposes its brief and inputs
    since its last completed turn name in `serves: P<n>`. One purpose's
    worker cannot hide another purpose left unattended, and a child reused for
    P2 no longer carries the P1 it finished. A child that serves only a
    revision carries none.
  - The thread's own background task carries only the purposes its
    description names in `serves: P<n>`. An unrelated watcher that never
    finishes hides nothing.
- It reads bb's store (`~/.bb/bb.db`) read-only rather than the bb CLI: at load
  ~290 each CLI call took 4-20 s, past Codex's 5 s Stop-hook budget, so the
  check would have failed open whenever the fleet was busy. A background task
  is running while its start (within 24 h) has no completion.
- The nudge lists the unattended purposes and allows three outcomes:
  continue the next authorized step, `mark … done --evidence`, or
  `mark … blocked-on-user --ask` for a decision only the user owns (money, an
  outward or irreversible effect, credentials, a genuine ambiguity). A status
  report is none of them.
- A blocked-on-user purpose counts as open again when the latest user-typed
  input in the transcript is newer than its mark. Inputs bb and hooks compose
  (`[bb …]`, `[from …]`, `[child of …]`, `[fleet …]`) don't count.
- A thread with child threads and no ledger is asked once per thread
  (`~/.local/state/agent-quality/closeout-ledger-nudged.json`) to record the
  user's purposes with `init`.
- A solo thread without a ledger also receives a continuation check when its
  final message explicitly reports unrun workflows/QA/E2E, an open purpose id, unfinished implementation,
  an unperformed next step, or offers to do reversible work. Quoted and fenced
  examples are excluded, Markdown bold status labels are recognized, and a
  report beginning "Paused as requested" retains the user's stop. Direct hook text and bounded Claude/Codex transcript
  fallbacks are supported; tool output and reasoning are excluded.
- The check asks the agent to load `finish-the-job` and `meaningful-tests`,
  continue actionable authorized work, and prepare independent steps while a
  decision is pending. It does not authorize scope or permission changes. If
  every remaining step needs the user, retain the precise approval request.
- The registered `qa-stop-hook.sh` command needs a host timeout of at least
  15 seconds. Its repository lookup alone permits 5 seconds, before the
  evidence/closeout stages; a 5-second host limit can discard their result on
  a loaded host. `hook-timeouts.py` checks/applies this alongside the existing
  PreToolUse budget, preserving unrelated settings and backing up changes.
- `stop_hook_active` (the retry after a nudge), an unreadable ledger and
  unreadable thread state allow the stop. Without a BB thread id the bounded
  message check still runs, but no BB ledger or thread state is read. Native
  Codex hooks can lack the shell tool's `BB_THREAD_ID`; their own Stop result
  resumes that native session. Metadata-only audit records may include its
  session id so a live interception can be matched to the provider session.
- Each decision goes to `~/.local/state/agent-quality/events.jsonl` as a
  `closeout-stop` event with the thread, branch, decision and purpose IDs,
  never text.
- Kill rule, set before shipping: after 20 blocks, read what each agent did
  next. If more than a quarter stopped again with no new action, narrow the
  check or remove it.

This is a bounded continuation check, not proof that the model completed the
workflow. The retry can still end, state-reading failures still allow a stop,
and implicit unfinished work may not match the solo text patterns. Product
completion still requires the full user journey and its evidence.
