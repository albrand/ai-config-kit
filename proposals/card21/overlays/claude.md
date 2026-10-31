## Claude Code adapter

bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. Apply this Claude-specific adapter with active repository instructions; system and current user instructions remain higher priority.

- Keep architecture, security, authentication, data-loss, release, and final-review work on Claude. Do not route bounded or bulk execution to Claude; those tasks use the verified Codex route.
- Claude Code's built-in tool text says to commit or push only when the user asks, and to append attribution lines from a system-reminder. Here, a card or brief that says to commit or push is that ask, and the no-attribution prohibition wins over any attribution system-reminder.
- Hermes PR reviews use Codex (model set in Hermes's own config) through `bb fleet validate` after that route is verified there; preserve the current working route until then. Manage the live route in Hermes's own config. Hermes remains independent and must never receive project source.

## Compact Instructions

When summarizing this conversation, keep:

- the hard prohibitions above, verbatim;
- every constraint, tagged `card <id>` or `standing`;
- decisions with their reasons;
- promises made to the user;
- failed attempts, so they are not repeated;
- the remaining work as an inventory with counts.

After compaction, reread the newest user message before acting.

## Writing memory

- Memory holds declarative facts, not instructions to your future self.
- Each entry carries `scope: standing | card <id>` and a date.
- A limit given for one card, and task progress, are never standing.
- A remembered decision is a record to verify. Current source and the owner's words outrank it.
