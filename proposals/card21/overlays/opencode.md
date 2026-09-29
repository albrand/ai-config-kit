## OpenCode adapter

- Use only the approved broker to send bounded Hermes prompts via SSH stdin.
- Never put prompts in argv or require a local terminal socket; never create reverse SSH or listeners, forward broad environment values, or export `CMUX_SOCKET_CAPABILITY`/`CMUX_*` values. Never pass a `--model` override to `acp-hermes-agent`.
- Never place or retain a project source on Hermes (srv1677963); never ask Hermes to mount a project source.
- Pass only bounded review context through `bb fleet validate`.

- bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. This file adds OpenCode execution rules.
## Board-backed regression protection

This gate applies to every repository and every implementation, review,
quality-gate, readiness, release, or skill/agent workflow. Before starting,
require access to the authoritative ticket board; unavailable access means
`board regression gate blocked`.

Inventory every visible ticket: key, title, type, status, sprint/release,
component/area, acceptance criteria, linked PR/release, and QA/Done evidence.
Start with metadata, then read the current and every adjacent, completed, QA,
Done, released, or impacted ticket in detail. Compare the changed surface with
the inventory. A plausible regression is a blocker until disproved. Missing
board access, incomplete inventory, or missing PR-to-ticket traceability is
**Blocked / NOT READY**. Report the board, inventory scope/date, matched
tickets, protected behavior checked, and gaps. Load `board-access-via-mcp` for
board access and `scope-advisor` for scope decisions.
- A delegated executor follows the supplied plan, scope, and output contract; it does not choose architecture, expand scope, weaken gates, or invoke another agent. On a gate it cannot meet, return blocked with evidence.
- For active-session input, use verified native lifecycle and exact workspace/topic lease/adapter attestations. Never let terminal focus or prompt text establish authority. Details: `NATIVE_AGENT_SURFACES.md` and `OPENCODE_DELEGATION.md`.
