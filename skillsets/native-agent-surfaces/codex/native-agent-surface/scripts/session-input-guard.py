#!/usr/bin/env python3
"""Session input admission guard: portable workspace/topic isolation.

A **metadata-only** admission guard that decides how an incoming input relates
to an active lease. It implements the portable workspace/topic isolation
contract: same exact lease/topic clarifications may be accepted; authenticated
same-lease redirects may update scope with an epoch bump; unrelated
same-workspace work queues or routes to a fresh session; cross-workspace work
routes and never interrupts; supersede requires authenticated user authority
plus an exact lease/workspace/session/epoch target and a validated resume-packet
reference; crash recovery is explicitly audited and can never masquerade as a
normal supersede.

The guard consumes **only** lease/envelope metadata (opaque full identifiers,
epoch, status, input class, attribution). It never accepts prompt bodies,
secrets, environment values, or ``CMUX_*`` values: the input schema is a strict
allowlist and any unknown or forbidden-named field fails closed. The lease is a
**routing guard / cross-check**, never a second write grant — the one worktree
write owner remains the sole source of mutation authority.

Input is JSON read from a file (``--input PATH``) or stdin (``--input -``).
Output is a single JSON decision on stdout. Exit codes: ``0`` for an accept /
queue / route decision, ``1`` for a deny, ``2`` for blocked (malformed or
fail-closed).

Run ``--selftest`` for offline fixture self-tests (no network, no writes).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# --------------------------------------------------------------------------- #
# Schema: strict allowlist (additionalProperties: false semantics)
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1

TOP_KEYS = frozenset({"envelope", "current_lease"})

ENVELOPE_KEYS = frozenset({
    "schema_version", "workspace_id", "session_id", "lease_id", "topic_id",
    "input_class", "attribution", "target_epoch", "resume_packet_ref",
    "resume_packet_validated", "topic_relation_verified",
    "source_workspace_id", "write_owner",
})

ATTRIBUTION_KEYS = frozenset({"kind", "authenticated", "authority"})

LEASE_KEYS = frozenset({
    "schema_version", "workspace_id", "session_id", "lease_id", "topic_id",
    "epoch", "status", "write_owner", "supersede_target_epoch",
    "resume_packet_ref",
})

INPUT_CLASSES = frozenset({
    "clarification", "redirect", "new_topic", "supersede", "handoff",
    "recovery",
})

ATTRIBUTION_KINDS = frozenset({
    "user", "group", "system", "dispatch", "terminal_injection", "unknown",
})

LEASE_STATUSES = frozenset({
    "active", "superseding", "superseded", "parked", "completed",
})

# Field-name fragments the guard must never accept. Defense-in-depth on top of
# the strict allowlist: even if a caller nests one of these under an allowed
# object, it is rejected explicitly.
FORBIDDEN_FIELD_FRAGMENTS = (
    "prompt", "body", "secret", "token", "password", "passwd", "credential",
    "api_key", "apikey", "private_key", "privatekey", "environment", "env_",
    "cmux", "socket", "cookie", "authorization",
)

# Decisions emitted by the guard.
DECISIONS = frozenset({
    "accept", "accept_redirect", "accept_supersede", "queue", "route_fresh",
    "route_cross_workspace", "deny", "recovery_audit", "blocked",
})

# Exit codes: 0 accept/queue/route, 1 deny, 2 blocked (fail-closed).
EXIT_OK = 0
EXIT_DENY = 1
EXIT_BLOCKED = 2


class GuardError(Exception):
    """Raised for recoverable, fail-closed (blocked) conditions."""


# --------------------------------------------------------------------------- #
# Validation: strict allowlist + forbidden-name scan
# --------------------------------------------------------------------------- #
def _check_forbidden_names(obj: dict[str, Any], where: str) -> None:
    """Reject any field name that resembles a forbidden content type."""
    for key in obj:
        low = str(key).lower()
        for frag in FORBIDDEN_FIELD_FRAGMENTS:
            if frag in low:
                raise GuardError(
                    f"{where}: forbidden field name {key!r} (resembles "
                    f"{frag!r}); the guard accepts metadata only"
                )


def _check_keys(obj: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(obj, dict):
        raise GuardError(f"{where}: must be a JSON object")
    _check_forbidden_names(obj, where)
    extra = set(obj.keys()) - allowed
    if extra:
        raise GuardError(
            f"{where}: unknown field(s): {sorted(extra)}; the guard accepts "
            "only declared metadata and fails closed on anything else"
        )


def _require_nonempty_str(obj: dict[str, Any], key: str, where: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise GuardError(f"{where}: {key} must be a non-empty string")
    return val.strip()


def _opt_nonempty_str(obj: dict[str, Any], key: str, where: str) -> str | None:
    if key not in obj or obj[key] is None:
        return None
    val = obj[key]
    if not isinstance(val, str) or not val.strip():
        raise GuardError(f"{where}: {key} must be a non-empty string or null")
    return val.strip()


def _require_int(obj: dict[str, Any], key: str, where: str) -> int:
    val = obj.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        raise GuardError(f"{where}: {key} must be an integer")
    return val


def _opt_int(obj: dict[str, Any], key: str, where: str) -> int | None:
    if key not in obj or obj[key] is None:
        return None
    return _require_int(obj, key, where)


def _require_bool(obj: dict[str, Any], key: str, where: str) -> bool:
    val = obj.get(key)
    if not isinstance(val, bool):
        raise GuardError(f"{where}: {key} must be a boolean")
    return val


def _opt_bool(obj: dict[str, Any], key: str, where: str,
              *, default: bool = False) -> bool:
    if key not in obj or obj[key] is None:
        return default
    return _require_bool(obj, key, where)


def validate_envelope(raw: Any) -> dict[str, Any]:
    _check_keys(raw, ENVELOPE_KEYS, "envelope")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise GuardError(
            f"envelope: schema_version must be {SCHEMA_VERSION}"
        )
    env: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": _require_nonempty_str(raw, "workspace_id", "envelope"),
        "session_id": _require_nonempty_str(raw, "session_id", "envelope"),
        "lease_id": _opt_nonempty_str(raw, "lease_id", "envelope"),
        "topic_id": _opt_nonempty_str(raw, "topic_id", "envelope"),
    }
    input_class = raw.get("input_class")
    if input_class not in INPUT_CLASSES:
        raise GuardError(
            f"envelope: input_class must be one of {sorted(INPUT_CLASSES)}"
        )
    env["input_class"] = input_class

    attr_raw = raw.get("attribution")
    env["attribution"] = validate_attribution(attr_raw)
    env["target_epoch"] = _opt_int(raw, "target_epoch", "envelope")
    env["resume_packet_ref"] = _opt_nonempty_str(
        raw, "resume_packet_ref", "envelope"
    )
    env["resume_packet_validated"] = _opt_bool(
        raw, "resume_packet_validated", "envelope"
    )
    env["topic_relation_verified"] = _opt_bool(
        raw, "topic_relation_verified", "envelope"
    )
    env["source_workspace_id"] = _opt_nonempty_str(
        raw, "source_workspace_id", "envelope"
    )
    env["write_owner"] = _opt_nonempty_str(raw, "write_owner", "envelope")
    return env


def validate_attribution(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GuardError("envelope.attribution: must be a JSON object")
    _check_keys(raw, ATTRIBUTION_KEYS, "envelope.attribution")
    kind = raw.get("kind")
    if kind not in ATTRIBUTION_KINDS:
        raise GuardError(
            f"envelope.attribution: kind must be one of "
            f"{sorted(ATTRIBUTION_KINDS)}"
        )
    return {
        "kind": kind,
        "authenticated": _require_bool(raw, "authenticated",
                                       "envelope.attribution"),
        "authority": _opt_nonempty_str(raw, "authority",
                                       "envelope.attribution"),
    }


def validate_lease(raw: Any) -> dict[str, Any]:
    _check_keys(raw, LEASE_KEYS, "current_lease")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise GuardError(
            f"current_lease: schema_version must be {SCHEMA_VERSION}"
        )
    lease: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": _require_nonempty_str(
            raw, "workspace_id", "current_lease"),
        "session_id": _require_nonempty_str(
            raw, "session_id", "current_lease"),
        "lease_id": _require_nonempty_str(
            raw, "lease_id", "current_lease"),
        "topic_id": _require_nonempty_str(
            raw, "topic_id", "current_lease"),
        "epoch": _require_int(raw, "epoch", "current_lease"),
    }
    if lease["epoch"] < 0:
        raise GuardError("current_lease: epoch must be >= 0")
    status = raw.get("status")
    if status not in LEASE_STATUSES:
        raise GuardError(
            f"current_lease: status must be one of {sorted(LEASE_STATUSES)}"
        )
    lease["status"] = status
    lease["write_owner"] = _opt_nonempty_str(raw, "write_owner", "current_lease")
    lease["supersede_target_epoch"] = _opt_int(
        raw, "supersede_target_epoch", "current_lease")
    lease["resume_packet_ref"] = _opt_nonempty_str(
        raw, "resume_packet_ref", "current_lease")
    return lease


def validate_payload(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw, dict):
        raise GuardError("input: must be a JSON object")
    _check_keys(raw, TOP_KEYS, "input")
    envelope = validate_envelope(raw.get("envelope"))
    current_lease = validate_lease(raw.get("current_lease"))
    return envelope, current_lease


# --------------------------------------------------------------------------- #
# Decision logic
# --------------------------------------------------------------------------- #
def _decision(
    decision: str,
    reason: str,
    *,
    input_class: str,
    requirements: list[str] | None = None,
    epoch_bump_required: bool = False,
    new_epoch: int | None = None,
    new_status: str | None = None,
    write_owner_crosscheck: str = "not_applicable",
    crash_recovery: bool = False,
    explicit_audit_required: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "decision": decision,
        "reason": reason,
        "input_class": input_class,
        "epoch_bump_required": epoch_bump_required,
        "new_epoch": new_epoch,
        "new_status": new_status,
        "write_owner_crosscheck": write_owner_crosscheck,
        "lease_is_routing_guard": True,
        "audit": {
            "crash_recovery": crash_recovery,
            "explicit_audit_required": explicit_audit_required,
        },
    }
    if requirements:
        out["requirements"] = list(requirements)
    return out


def _write_owner_crosscheck(env: dict[str, Any],
                            lease: dict[str, Any]) -> str:
    env_owner = env.get("write_owner")
    lease_owner = lease.get("write_owner")
    if env_owner is None or lease_owner is None:
        return "not_applicable"
    return "match" if env_owner == lease_owner else "mismatch"


def admit(envelope: dict[str, Any], current_lease: dict[str, Any]) -> dict[str, Any]:
    """Decide how an incoming input relates to the active lease.

    The lease is a routing guard / cross-check only. The one worktree write
    owner remains the sole source of mutation authority.
    """
    env_ws = envelope["workspace_id"]
    source_ws = envelope.get("source_workspace_id")
    lease_ws = current_lease["workspace_id"]
    input_class = envelope["input_class"]
    attr = envelope["attribution"]
    status = current_lease["status"]
    epoch = current_lease["epoch"]
    crosscheck = _write_owner_crosscheck(envelope, current_lease)

    # 1. Cross-workspace: always route without interrupting the current lease.
    if env_ws != lease_ws or (source_ws is not None and source_ws != lease_ws):
        return _decision(
            "route_cross_workspace",
            "cross-workspace input routes without interrupting the current "
            "lease",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )

    # A same-workspace ownership divergence is not advisory: delivery could
    # activate the wrong writer. Fail closed and let the owning adapter
    # reconcile its authoritative worktree ownership record first.
    if crosscheck == "mismatch":
        return _decision(
            "blocked",
            "write-owner metadata disagrees with the active lease; delivery "
            "is blocked pending authoritative ownership reconciliation",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
            requirements=["reconcile the owning adapter's worktree write owner"],
        )

    # 2. Recovery: explicitly audited; never masquerades as a normal supersede.
    if input_class == "recovery":
        return _decision(
            "recovery_audit",
            "crash recovery is explicitly audited and processed on a distinct "
            "path; it never masquerades as a normal supersede",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
            crash_recovery=True,
            explicit_audit_required=True,
            requirements=["explicit crash-recovery audit before any state change"],
        )

    # 3. Superseding transition: queue arrivals visibly during the transition.
    if status == "superseding":
        return _decision(
            "queue",
            "lease is in a superseding transition; arrivals are queued visibly "
            "until the validated resume packet replaces it",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )

    # 4. Supersede: requires authenticated user authority + exact target +
    #    validated resume-packet reference. Enters superseding on success.
    if input_class == "supersede":
        return _handle_supersede(envelope, current_lease, crosscheck)

    # 5. Handoff: a full handoff never replaces a working terminal. For a
    #    non-working lease it routes to a fresh session rather than reviving
    #    stale context in place.
    if input_class == "handoff":
        if status != "active":
            return _decision(
                "route_fresh",
                f"handoff targets a non-working {status!r} lease and routes "
                "to a fresh session",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
            )
        return _decision(
            "queue",
            "full handoff does not replace a working terminal; queued/routed "
            "without interrupting the active lease",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
            requirements=["handoff must target a non-working or completed lease "
                          "to take over; an active terminal is preserved"],
        )

    # 6. Missing / unattributed: queue visibly, never silently deliver.
    if attr["kind"] == "unknown":
        return _decision(
            "queue",
            "missing attribution; queued visibly and never silently delivered",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
            requirements=["resolved attribution before delivery"],
        )

    same_session = envelope["session_id"] == current_lease["session_id"]

    # 7. Different session (same workspace): unrelated work -> route fresh.
    if not same_session:
        return _decision(
            "route_fresh",
            "unrelated same-workspace work routes to a fresh session",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )

    same_lease = (envelope.get("lease_id") is not None
                  and envelope["lease_id"] == current_lease["lease_id"])

    # 8. Redirect: authenticated same-lease scope update with an epoch bump.
    if input_class == "redirect":
        if not same_lease:
            return _decision(
                "deny",
                "redirect requires an exact same-lease target",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
            )
        if status != "active":
            return _decision(
                "deny",
                f"redirect target lease is {status!r}, not active",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
            )
        if attr["kind"] != "user" or not attr["authenticated"]:
            return _decision(
                "queue",
                "redirect requires authenticated user authority; queued "
                "pending authentication",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
                requirements=["authenticated user authority"],
            )
        if not attr.get("authority"):
            return _decision(
                "blocked",
                "redirect authentication lacks a verified authority identity",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
                requirements=["verified user authority identity"],
            )
        target_epoch = envelope.get("target_epoch")
        if target_epoch is None or target_epoch != epoch:
            return _decision(
                "deny",
                f"stale epoch; redirect targets {target_epoch} but the lease "
                f"is at {epoch}",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
            )
        return _decision(
            "accept_redirect",
            "authenticated same-lease redirect accepted; scope update with an "
            "epoch bump",
            input_class=input_class,
            epoch_bump_required=True,
            new_epoch=epoch + 1,
            write_owner_crosscheck=crosscheck,
        )

    # 9. Different lease in the same session (not supersede/redirect).
    if not same_lease:
        if input_class == "new_topic":
            return _decision(
                "route_fresh",
                "new topic in the same session routes to a fresh session",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
            )
        return _decision(
            "queue",
            "different lease in the same session; queued visibly pending "
            "routing",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )

    # 10. Same lease.
    same_topic = (envelope.get("topic_id") is not None
                  and envelope["topic_id"] == current_lease["topic_id"])
    if not same_topic:
        if input_class == "new_topic":
            return _decision(
                "route_fresh",
                "different topic in the same lease routes to a fresh session",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
            )
        return _decision(
            "queue",
            "different topic in the same lease; queued visibly pending routing",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )

    # Only an active lease may accept an in-place clarification. Completed,
    # parked, or superseded leases must not be silently revived.
    if status != "active":
        return _decision(
            "queue",
            f"exact target lease is {status!r}, not active; queued visibly "
            "instead of reviving or interrupting stale context",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )

    # 11. Same active lease + same topic. Dispatch and direct terminal injection are
    #     clarification-class by default: they are accepted as clarifications
    #     but can never supersede or redirect (those require authenticated user
    #     authority, checked above).
    if input_class == "clarification":
        if not envelope.get("topic_relation_verified"):
            return _decision(
                "queue",
                "same-target clarification lacks an adapter-verified topic "
                "relationship; queued instead of trusting terminal destination",
                input_class=input_class,
                write_owner_crosscheck=crosscheck,
                requirements=["adapter-verified topic relationship"],
            )
        note = ""
        if attr["kind"] in ("dispatch", "terminal_injection"):
            note = (f" ({attr['kind']} attribution is clarification-class by "
                    "default)")
        return _decision(
            "accept",
            "exact same-lease/topic input accepted as a clarification" + note,
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )
    if input_class == "new_topic":
        return _decision(
            "route_fresh",
            "new topic routes to a fresh session",
            input_class=input_class,
            write_owner_crosscheck=crosscheck,
        )
    # Any remaining uncertainty: queue visibly.
    return _decision(
        "queue",
        "uncertain same-lease/topic input; queued visibly and never silently "
        "delivered",
        input_class=input_class,
        write_owner_crosscheck=crosscheck,
    )


def _handle_supersede(envelope: dict[str, Any],
                      current_lease: dict[str, Any],
                      crosscheck: str) -> dict[str, Any]:
    attr = envelope["attribution"]
    epoch = current_lease["epoch"]
    status = current_lease["status"]

    # Group or unattributed messages never supersede.
    if attr["kind"] != "user" or not attr["authenticated"]:
        return _decision(
            "deny",
            "supersede requires authenticated user authority; group or "
            "unattributed messages never supersede",
            input_class="supersede",
            write_owner_crosscheck=crosscheck,
        )
    if not attr.get("authority"):
        return _decision(
            "blocked",
            "supersede authentication lacks a verified authority identity",
            input_class="supersede",
            write_owner_crosscheck=crosscheck,
            requirements=["verified user authority identity"],
        )

    # Exact lease/workspace/session target.
    target_epoch = envelope.get("target_epoch")
    if (envelope.get("lease_id") != current_lease["lease_id"]
            or envelope["workspace_id"] != current_lease["workspace_id"]
            or envelope["session_id"] != current_lease["session_id"]):
        return _decision(
            "deny",
            "supersede requires an exact lease/workspace/session target",
            input_class="supersede",
            write_owner_crosscheck=crosscheck,
        )

    if status != "active":
        return _decision(
            "deny",
            f"supersede target lease is {status!r}, not active",
            input_class="supersede",
            write_owner_crosscheck=crosscheck,
        )

    # Exact epoch target (stale or future epochs are denied).
    if target_epoch is None or target_epoch != epoch:
        return _decision(
            "deny",
            f"stale epoch; supersede targets {target_epoch} but the lease is "
            f"at {epoch}",
            input_class="supersede",
            write_owner_crosscheck=crosscheck,
        )

    # Validated resume-packet reference required before replacement.
    if (not envelope.get("resume_packet_ref")
            or not envelope.get("resume_packet_validated")):
        return _decision(
            "deny",
            "supersede requires both a resume-packet reference and an explicit "
            "validation attestation from the owning adapter before replacement",
            input_class="supersede",
            write_owner_crosscheck=crosscheck,
            requirements=["validated resume-packet reference"],
        )

    return _decision(
        "accept_supersede",
        "supersede authorized; the lease enters the superseding transition and "
        "arrivals are queued until the validated resume packet replaces it",
        input_class="supersede",
        epoch_bump_required=True,
        new_epoch=epoch + 1,
        new_status="superseding",
        write_owner_crosscheck=crosscheck,
        requirements=["validated resume-packet reference present"],
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _exit_for(decision: str) -> int:
    if decision == "deny":
        return EXIT_DENY
    if decision == "blocked":
        return EXIT_BLOCKED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="session-input-guard.py",
        description="Metadata-only admission guard for portable "
                    "workspace/topic lease isolation. Never accepts prompt "
                    "bodies, secrets, env values, or CMUX values.",
    )
    parser.add_argument("--input", default="-",
                        help="JSON payload path, or '-' for stdin")
    args = parser.parse_args(argv)

    if args.input == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.input, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            sys.stderr.write(f"blocked: cannot read input: {exc}\n")
            return EXIT_BLOCKED

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        sys.stdout.write(json.dumps({
            "decision": "blocked",
            "reason": f"input is not valid JSON: {exc}",
            "lease_is_routing_guard": True,
        }, indent=2, sort_keys=True) + "\n")
        return EXIT_BLOCKED

    try:
        envelope, current_lease = validate_payload(payload)
    except GuardError as exc:
        sys.stdout.write(json.dumps({
            "decision": "blocked",
            "reason": str(exc),
            "lease_is_routing_guard": True,
        }, indent=2, sort_keys=True) + "\n")
        return EXIT_BLOCKED

    result = admit(envelope, current_lease)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return _exit_for(result["decision"])


# --------------------------------------------------------------------------- #
# Offline self-test (no network, no writes)
# --------------------------------------------------------------------------- #
def _base_env(**over: Any) -> dict[str, Any]:
    env: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": "ws-full-aaa",
        "session_id": "sess-full-bbb",
        "lease_id": "lease-full-ccc",
        "topic_id": "topic-full-ddd",
        "input_class": "clarification",
        "attribution": {"kind": "user", "authenticated": True,
                        "authority": "user-1"},
        "target_epoch": None,
        "resume_packet_ref": None,
        "resume_packet_validated": False,
        "topic_relation_verified": True,
        "source_workspace_id": None,
        "write_owner": None,
    }
    env.update(over)
    return env


def _base_lease(**over: Any) -> dict[str, Any]:
    lease: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": "ws-full-aaa",
        "session_id": "sess-full-bbb",
        "lease_id": "lease-full-ccc",
        "topic_id": "topic-full-ddd",
        "epoch": 5,
        "status": "active",
        "write_owner": "owner-1",
        "supersede_target_epoch": None,
        "resume_packet_ref": None,
    }
    lease.update(over)
    return lease


def _run(env: dict[str, Any], lease: dict[str, Any]) -> dict[str, Any]:
    e, l = validate_envelope(dict(env)), validate_lease(dict(lease))
    return admit(e, l)


def selftest() -> int:
    """Offline fixture-based self-test covering all required cases."""
    checks: list[tuple[str, bool, str]] = []

    def case(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    # 1. Exact clarification accepted.
    r = _run(_base_env(), _base_lease())
    case("exact clarification accepted",
         r["decision"] == "accept", r["decision"])

    # 2. Authenticated exact redirect accepted with epoch bump.
    r = _run(_base_env(input_class="redirect", target_epoch=5), _base_lease())
    case("redirect accepted with epoch bump",
         r["decision"] == "accept_redirect" and r["epoch_bump_required"]
         and r["new_epoch"] == 6, r["decision"])

    # 3. Different topic queued/routed fresh.
    r = _run(_base_env(input_class="new_topic",
                      topic_id="topic-other"),
             _base_lease())
    case("different topic routed fresh",
         r["decision"] == "route_fresh", r["decision"])
    r = _run(_base_env(input_class="clarification",
                      topic_id="topic-other"),
             _base_lease())
    case("clarification for different topic queued",
         r["decision"] == "queue", r["decision"])

    # 4. Cross-workspace routed.
    r = _run(_base_env(workspace_id="ws-other"), _base_lease())
    case("cross-workspace routed",
         r["decision"] == "route_cross_workspace", r["decision"])

    # 5. Group supersede denied.
    r = _run(_base_env(input_class="supersede",
                      attribution={"kind": "group", "authenticated": True,
                                   "authority": None},
                      target_epoch=5),
             _base_lease())
    case("group supersede denied", r["decision"] == "deny", r["decision"])

    # 6. Stale epoch denied.
    r = _run(_base_env(input_class="supersede", target_epoch=3,
                      resume_packet_ref="rp-1",
                      resume_packet_validated=True),
             _base_lease())
    case("stale epoch supersede denied",
         r["decision"] == "deny", r["decision"])
    r = _run(_base_env(input_class="redirect", target_epoch=99),
             _base_lease())
    case("future epoch redirect denied",
         r["decision"] == "deny", r["decision"])

    # 7. Superseding lease queues.
    r = _run(_base_env(), _base_lease(status="superseding"))
    case("superseding lease queues", r["decision"] == "queue",
         r["decision"])

    # 8. Missing attribution queues.
    r = _run(_base_env(attribution={"kind": "unknown", "authenticated": False,
                                    "authority": None}),
             _base_lease())
    case("missing attribution queued",
         r["decision"] == "queue", r["decision"])

    # 9. Full handoff does not replace a working terminal.
    r = _run(_base_env(input_class="handoff"), _base_lease())
    case("handoff does not replace working terminal",
         r["decision"] == "queue", r["decision"])

    # 10. Crash recovery audited, not supersede.
    r = _run(_base_env(input_class="recovery"), _base_lease())
    case("recovery audited not supersede",
         r["decision"] == "recovery_audit"
         and r["audit"]["crash_recovery"] is True
         and r["audit"]["explicit_audit_required"] is True,
         r["decision"])

    # 11. Authenticated supersede with all requirements accepted.
    r = _run(_base_env(input_class="supersede", target_epoch=5,
                      resume_packet_ref="rp-validated",
                      resume_packet_validated=True),
             _base_lease())
    case("supersede accepted enters superseding",
         r["decision"] == "accept_supersede"
         and r["new_status"] == "superseding" and r["new_epoch"] == 6,
         r["decision"])

    # 12. Supersede without resume packet denied.
    r = _run(_base_env(input_class="supersede", target_epoch=5),
             _base_lease())
    case("supersede without resume packet denied",
         r["decision"] == "deny", r["decision"])

    # 13. Dispatch is clarification-class by default (accepted as clarification).
    r = _run(_base_env(input_class="clarification",
                      attribution={"kind": "dispatch", "authenticated": False,
                                   "authority": None}),
             _base_lease())
    case("dispatch clarification accepted",
         r["decision"] == "accept", r["decision"])

    # 13b. Dispatch-attributed supersede is denied (never user authority).
    r = _run(_base_env(input_class="supersede",
                      attribution={"kind": "dispatch", "authenticated": False,
                                   "authority": None},
                      target_epoch=5, resume_packet_ref="rp-1",
                      resume_packet_validated=True),
             _base_lease())
    case("dispatch supersede denied",
         r["decision"] == "deny", r["decision"])

    # 14. Unauthenticated redirect queued.
    r = _run(_base_env(input_class="redirect", target_epoch=5,
                      attribution={"kind": "user", "authenticated": False,
                                   "authority": None}),
             _base_lease())
    case("unauthenticated redirect queued",
         r["decision"] == "queue", r["decision"])

    # 15. Different session routes fresh.
    r = _run(_base_env(session_id="sess-other"), _base_lease())
    case("different session routes fresh",
         r["decision"] == "route_fresh", r["decision"])

    # 16. Write-owner divergence blocks delivery.
    r = _run(_base_env(write_owner="owner-other"), _base_lease())
    case("write-owner mismatch blocked",
         r["decision"] == "blocked"
         and r["write_owner_crosscheck"] == "mismatch", r["decision"])

    # 17. Unknown field fails closed (blocked).
    try:
        validate_payload({"envelope": dict(_base_env(), oops=1),
                          "current_lease": _base_lease()})
        case("unknown field blocked", False)
    except GuardError:
        case("unknown field blocked", True)

    # 18. Forbidden field name fails closed (blocked).
    try:
        validate_payload({"envelope": dict(_base_env(), prompt_body="x"),
                          "current_lease": _base_lease()})
        case("forbidden prompt field blocked", False)
    except GuardError:
        case("forbidden prompt field blocked", True)

    # 19. Env-value-named field fails closed.
    try:
        validate_payload({"envelope": dict(_base_env(), env_value="SECRET"),
                          "current_lease": _base_lease()})
        case("forbidden env field blocked", False)
    except GuardError:
        case("forbidden env field blocked", True)

    # 20. CMUX-named field fails closed.
    try:
        validate_payload({"envelope": dict(_base_env(),
                                           cmux_socket_capability="x"),
                          "current_lease": _base_lease()})
        case("forbidden cmux field blocked", False)
    except GuardError:
        case("forbidden cmux field blocked", True)

    # 21. Invalid input_class fails closed.
    try:
        validate_envelope(dict(_base_env(), input_class="bogus"))
        case("invalid input_class blocked", False)
    except GuardError:
        case("invalid input_class blocked", True)

    # 22. Non-integer epoch fails closed.
    try:
        validate_lease(dict(_base_lease(), epoch="five"))
        case("non-integer epoch blocked", False)
    except GuardError:
        case("non-integer epoch blocked", True)

    failed = 0
    for name, cond, detail in checks:
        failed += 0 if cond else 1
        print(f"[{'ok' if cond else 'FAIL'}] {name}" + (
            f" - {detail}" if detail and not cond else ""))
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
