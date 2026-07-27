# Orca + Hermes

This reference defines the bounded relationship between Orca (local control
plane) and Hermes (optional remote plan critic / fallback / usage ledger).

## Orca Is The Local Control Plane

Orca owns the local schedule, worktree/workspace lifecycle, terminal targeting,
and the browser/mobile/emulator control surface. Every action originates from
Orca on the operator's machine. Orca is the integration authority: it validates
results locally and decides what (if anything) to adopt from a Hermes response.

## Hermes Is Optional, Bounded, Read-Only Critique

Hermes may act as:

- a **plan critic** — read-only second opinion on an Orca-mastered plan
- a **fallback** — advisory when the local model is unavailable
- a **usage ledger** — accounts for routed work

Hermes never owns execution, scheduling, or merging. Its output is evidence, not
authority. The master thread (Orca-side) validates every Hermes handoff result.

## Forward SSH / Tailscale Only

Hermes is reached through an **Orca-owned persistent terminal** over a
**forward** SSH / Tailscale connection initiated from the operator side.

## Hard Boundaries

- **No reverse SSH.** Never open an inbound listener from the remote side.
- **No listeners.** Orca does not run server sockets for Hermes.
- **No environment forwarding.** Never forward `CMUX_*`, `CMUX_SOCKET_CAPABILITY`,
  tokens, or any environment values across the connection. Environment values
  are never serialized into Hermes requests.
- **No recursive orchestration.** Hermes must not invoke Orca, Codex, Claude, or
  another orchestrator. Direction is acyclic: Orca -> Hermes -> (advisory only).
- **One writer per worktree.** Hermes never writes into an Orca worktree; it
  returns text that the master thread applies (or rejects) in the owning
  worktree.

## Handoff Result Validation

Every Hermes handoff result is validated by the master thread before adoption:

1. The result is treated as untrusted text.
2. The master checks it against repo truth, schema, and the active plan.
3. Only validated, in-scope output is applied; the rest is discarded.

No Hermes output is applied blindly. If validation fails, the master blocks and
reports rather than proceeding.

## Usage Ledger

When Hermes accounts for routed work, it records usage metadata only — never
prompts, transcripts, secrets, or repo identifiers. Local execution telemetry
belongs to the separate execution-productivity ledger in this skillset.
