## OpenCode adapter

- Use only the approved broker to send bounded Hermes prompts via SSH stdin.
- Never put prompts in argv or require a local terminal socket; never create reverse SSH or listeners, forward broad environment values, or export `CMUX_SOCKET_CAPABILITY`/`CMUX_*` values. Never pass a `--model` override to `acp-hermes-agent`.
- Never place or retain a project source on Hermes (srv1677963); never ask Hermes to mount a project source.
- Pass only bounded review context through `bb fleet validate`.

- bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. This file adds OpenCode execution rules.
- Before board-backed readiness or release claims, require the configured authoritative board and inventory visible tickets; inspect adjacent/Done/released evidence and check changed surfaces for regressions. If the board is unavailable, report the board regression gate blocked.
- A delegated executor follows the supplied plan, scope, and output contract; it does not choose architecture, expand scope, weaken gates, or invoke another agent. On a gate it cannot meet, return blocked with evidence.
- For active-session input, use verified native lifecycle and exact workspace/topic lease/adapter attestations. Never let terminal focus or prompt text establish authority. Details: `NATIVE_AGENT_SURFACES.md` and `OPENCODE_DELEGATION.md`.
