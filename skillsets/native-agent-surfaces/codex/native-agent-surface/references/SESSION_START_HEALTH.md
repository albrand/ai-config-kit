# Session-Start Health Contract

A model-neutral preflight contract for **session-start health**. Before an agent
session is launched or resumed, an adapter *may* expose a report-only check that
catches two failure classes early:

1. **Broken SessionStart hook prerequisites** — a hook command whose runtime or
   referenced target no longer exists, a malformed hook manifest, or a duplicate
   SessionStart invocation that will fire more than once.
2. **Stale sessions** — a process already running whose start time predates an
   on-disk update to the executable or an enabled hook manifest, so its
   in-memory hooks no longer match what is on disk.

This file defines the **neutral** rules. It deliberately does **not** encode any
one tool's command shapes, config file layout, or CLI surface. Tool-specific
adapters (e.g. the Claude doctor at `scripts/claude-session-hook-doctor.py`)
implement the contract for their host.

## The five neutral checks

A session-start preflight, when offered, reports against these dimensions:

| Dimension | Neutral question |
| --- | --- |
| **Hook identity** | Which hook manifest(s) declare a session-start command for this session/tool? |
| **Invocation uniqueness** | Is the same session-start command declared more than once for the same event in the same manifest? |
| **Runtime presence** | Does the program that the hook command launches actually exist (without executing it)? |
| **Path resolvability** | Do literal path references in the command resolve, and do their targets exist? |
| **Restart-required state** | Is a live session process older than an updated executable or hook manifest on disk? |

Nothing in the neutral contract assumes how a tool stores hooks, how it is
invoked, or what its metadata commands look like. Those belong to the adapter.

## Hard safety boundary (shared by every adapter)

- **Report-only.** No repair, no mutation, no writing to the user's home, plugin
  cache, or any session state. A preflight never "fixes" a hook.
- **Never execute an arbitrary hook command.** Commands are tokenized (e.g. with
  `shlex`) and inspected, never run, to validate runtime presence and path
  resolvability.
- **No `shell=True`**, no interpolation of captured command text into a shell.
  Treat every captured command string as **untrusted**.
- **Never serialize environment values** (`CMUX_*`, `PATH` values, etc.). A
  runtime expressed as an environment reference is reported as *unverified*, not
  resolved by reading the environment.
- **Bounded subprocess.** Any metadata query the adapter runs against the host
  tool must be a read-only metadata command under a timeout.
- **Keep targets inside the owning root.** A literal path reference anchored at a
  manifest/plugin root must stay within that root; an escaping reference is an
  error, not a resolution.
- **Never claim the in-memory process version.** A stale-process comparison uses
  only process start time vs. on-disk artifact mtime — it never asserts what
  version a running process has loaded.

## Report shape (neutral)

A preflight report distinguishes:

- `healthy` — no issues found.
- `warnings` — non-fatal concerns (duplicate invocation, env-referenced runtime
  that could not be verified, an unparsed process start time, a missing
  best-effort probe).
- `errors` — broken prerequisites (unreadable/malformed manifest, missing plugin
  root, missing runtime, missing or escaping target).
- `restart_required` — an advisory that a live process predates an updated
  artifact. **A restart advisory alone is not an error.**

Exit behavior is adapter-defined but must follow the neutral rule: exit nonzero
for errors; a restart advisory alone may remain exit 0 unless the caller opts
into a strict mode.

## Recovery guidance (neutral)

Because session-start hooks load only at session start, the only correct
remediation for a stale session or an updated hook is:

1. Update the host tool / plugin through its **official** command (never patch a
   cache by hand).
2. **Exit** the affected session.
3. **Resume the exact session id** (full id) — or start a new one. Hooks are not
   reloaded into an already-running process.
4. Preserve any unsent input before exiting; never suppress a failure to force a
   resume.

## Claude adapter

The Claude-specific implementation is
`scripts/claude-session-hook-doctor.py`. It is stdlib-only and report-only, and
follows every rule above. The adapter requires Claude Code `2.1.211` or newer;
older versions fail preflight because their session-start behavior is not a
safe baseline.

Static preflight proves that a literal `CLAUDE_PLUGIN_ROOT` reference resolves
against the plugin install root reported by Claude. It cannot prove that a
particular launcher injected that variable into a newly started hook process.
The runtime proof is a fresh launch/resume with no SessionStart failure in the
native surface or debug log.

When process discovery exposes only a basename instead of an exact executable
path, an mtime mismatch is reported as `restart_suspected`, not
`restart_required`. Confirm the target through the native surface using its full
workspace/surface UUID and exact session id before restarting it.

See the adapter's `--help` and the Session-Start Health section of `SKILL.md`.
