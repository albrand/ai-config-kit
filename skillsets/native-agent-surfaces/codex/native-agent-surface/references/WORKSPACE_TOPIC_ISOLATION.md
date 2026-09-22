# Workspace / Topic Isolation

This reference defines the **portable, host-neutral contract** for isolating an
active agent's work by workspace, session, lease, and topic. It is evaluated by
the metadata-only admission guard
`scripts/session-input-guard.py`, which consumes only lease/envelope metadata
and **never** accepts prompt bodies, secrets, environment values, or
`CMUX_*` values.

The lease schema is `schema/workspace-topic-lease.v1.json`.

The guard is a deterministic decision engine, not the delivery transport. The
owning adapter MUST invoke it before delivery and honor `queue`, `route_*`,
`deny`, `recovery_audit`, and `blocked`; otherwise this contract is not enforced.

## Why Isolation

Without an isolation contract, an unrelated input, a stale arrival, or a crash
recovery can silently replace or interrupt working work. This contract makes
every routing decision explicit: accept, queue, route fresh, route
cross-workspace, deny, or audit — never a silent delivery.

## Lease Model

Each active agent has a **lease** keyed by opaque full identifiers:

- `workspace_id` — the workspace the work belongs to.
- `session_id` — the session within the workspace.
- `lease_id` — the lease within the session.
- `topic_id` — the topic the lease is working on.

Identifiers are **host-neutral opaque full identifiers**, not assumed UUIDs.
The guard validates only that they are non-empty strings; format enforcement
belongs to the owning adapter.

A lease carries a **monotonic epoch** (integer, `>= 0`) bumped on accepted
redirects and supersedes to invalidate stale arrivals, and a **status**:

| Status | Meaning |
| --- | --- |
| `active` | The lease is the working target; clarifications are accepted. |
| `superseding` | A supersede is in progress; arrivals are queued visibly. |
| `superseded` | Replaced; no longer the active target. |
| `parked` | Suspended; not currently working. |
| `completed` | Finished; not interruptible. |

## Input Classes

Inputs classify into one of six classes:

| Class | Default handling |
| --- | --- |
| `clarification` | Accepted only for an exact active same-lease/topic target with a verified topic relationship. |
| `redirect` | Authenticated same-lease scope update with an epoch bump. |
| `new_topic` | Routes to a fresh session (unrelated work). |
| `supersede` | Replaces the active lease (strict requirements). |
| `handoff` | Routes/queues; never replaces a working terminal. |
| `recovery` | Explicitly audited; never masquerades as a supersede. |

**Dispatch and direct terminal injection are clarification-class by default.**
They are modeled as attribution kinds (`dispatch`, `terminal_injection`):
accepted as clarifications only with a verified topic relationship, and they can
never supersede or redirect because those require authenticated user authority.

## Admission Rules

1. **Cross-workspace routes without interrupting.** An input whose target
   `workspace_id` or declared `source_workspace_id` differs from the active
   lease is routed away; it never interrupts the current lease.
2. **Crash recovery is audited.** A `recovery` input is processed on a distinct
   audited path with `explicit_audit_required`. It never masquerades as a normal
   supersede.
3. **Superseding transition queues.** While a lease is `superseding`, all
   arrivals are queued visibly until the validated resume packet replaces it.
4. **Supersede requires the full chain of authority:**
   - authenticated **user** authority with a verified authority identity
     supplied by the owning adapter (group or unattributed never supersede),
   - exact `lease_id` + `workspace_id` + `session_id` target,
   - exact `target_epoch` == current epoch (stale or future denied),
   - the target lease must be `active`, and
   - a resume-packet reference plus an explicit validation attestation from the
     owning adapter before replacement.
   
   On success the lease enters `superseding` and the epoch bumps.
5. **Handoff does not replace a working terminal.** A full handoff queues or
   routes without interrupting an active lease.
6. **Missing attribution queues.** An `unknown`-attributed input is queued
   visibly and never silently delivered.
7. **Unrelated same-workspace work routes fresh.** A different session or a
   different topic routes to a fresh session.
8. **Redirect requires authenticated user authority** with a verified authority
   identity for an exact same-lease target that is `active`, plus an exact
   current epoch; on success the epoch bumps. A missing, stale, or mismatched
   epoch is denied.
9. **Only an active exact same-lease/topic target with an adapter-verified topic
   relationship accepts a clarification.** Merely arriving in a terminal does
   not prove topic relation. A missing attestation, or a parked, superseded, or
   completed lease, queues the arrival instead of silently changing or reviving
   context.

## Epoch Discipline

The epoch is monotonic. A `redirect` and an accepted `supersede` both require an
exact current target epoch and bump it by one. Any subsequent arrival that
targets the old epoch is denied as stale. The guard never auto-resolves a stale
epoch; it reports the mismatch.

## Write Ownership

The **one worktree write owner** is the sole source of mutation authority. The
lease is a **routing guard / cross-check**, not a second write grant. The guard
reports a `write_owner_crosscheck` (`match` | `mismatch` | `not_applicable`)
so a caller can detect divergence. A same-workspace mismatch blocks delivery
until the owning adapter reconciles its authoritative write-owner record. The
guard itself never grants or revokes write authority.

## Trusted Metadata Preconditions

The owning adapter, not the model and not the prompt text, MUST construct the
envelope from its control-plane records. In particular, it must set
`attribution.authenticated`, `attribution.authority`, and
`resume_packet_validated` only after verifying them at their authoritative
boundaries. It must set `topic_relation_verified` only from an explicit thread /
topic binding or an equivalent trusted routing decision — never merely because
the input arrived at the current terminal. The guard validates and combines
those attestations; it does not authenticate a human, inspect a resume packet,
or semantically classify prompt text itself. An adapter that copies these fields
from user-authored prompt content defeats the contract.

## Metadata-Only Boundary

The guard's input is a strict allowlist. It fails closed (`blocked`) on:

- any unknown field,
- any field name resembling a forbidden content type (`prompt`, `body`,
  `secret`, `token`, `password`, `credential`, `env`, `cmux`, `socket`, …),
- malformed JSON, wrong types, or missing required identifiers.

It never reads prompt bodies, secrets, environment values, or `CMUX_*` values.

## Guard Interface

```sh
# Decide from a JSON file
python3 scripts/session-input-guard.py --input envelope.json

# Decide from stdin
echo "$METADATA" | python3 scripts/session-input-guard.py --input -

# Offline self-test
python3 scripts/session-input-guard.py --selftest
```

Input shape (metadata only):

```json
{
  "envelope": {
    "schema_version": 1,
    "workspace_id": "ws-full-...",
    "session_id": "sess-full-...",
    "lease_id": "lease-full-...",
    "topic_id": "topic-full-...",
    "input_class": "clarification",
    "attribution": {"kind": "user", "authenticated": true, "authority": "user-1"},
    "target_epoch": 5,
    "resume_packet_ref": null,
    "resume_packet_validated": false,
    "topic_relation_verified": true,
    "source_workspace_id": null,
    "write_owner": "owner-1"
  },
  "current_lease": {
    "schema_version": 1,
    "workspace_id": "ws-full-...",
    "session_id": "sess-full-...",
    "lease_id": "lease-full-...",
    "topic_id": "topic-full-...",
    "epoch": 5,
    "status": "active",
    "write_owner": "owner-1",
    "supersede_target_epoch": null,
    "resume_packet_ref": null
  }
}
```

Decision shape:

```json
{
  "decision": "accept",
  "reason": "exact same-lease/topic input accepted as a clarification",
  "input_class": "clarification",
  "epoch_bump_required": false,
  "new_epoch": null,
  "new_status": null,
  "write_owner_crosscheck": "match",
  "lease_is_routing_guard": true,
  "audit": {"crash_recovery": false, "explicit_audit_required": false}
}
```

Decisions: `accept`, `accept_redirect`, `accept_supersede`, `queue`,
`route_fresh`, `route_cross_workspace`, `deny`, `recovery_audit`, `blocked`.

Exit codes: `0` accept/queue/route, `1` deny, `2` blocked (fail-closed).
