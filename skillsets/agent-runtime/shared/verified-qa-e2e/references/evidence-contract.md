# QA/E2E evidence contract

Keep this packet private and free of credentials, cookies, session tokens, and
vendor-specific secret links.

```json
{
  "schema_version": 1,
  "operation": "publish_qa_instructions",
  "reasoning_effort": "medium",
  "actor": {
    "verified": true,
    "persona": "vendor",
    "surface": "Vendor Portal",
    "environment": "development"
  },
  "entrypoint": {
    "verified": true,
    "route": "visible route description without secrets",
    "evidence": "private snapshot or observation reference"
  },
  "authentication": {
    "required": true,
    "initial_state": "logged_out",
    "state": "authenticated",
    "evidence": "private observation reference",
    "test_identity_discovery": {
      "checked": true,
      "found": true,
      "attempted": true,
      "evidence": "repository seed/setup reference without credentials"
    },
    "identities": [
      {
        "label": "qa.vendor",
        "ownership_checked": true,
        "ownership_evidence": "CI workflows and e2e setup/fixtures searched; no suite uses qa.vendor",
        "owned_by_automation": false
      }
    ]
  },
  "prerequisites": {
    "verified": true,
    "evidence": "private prerequisite check",
    "items": [
      {
        "name": "vendor portal link",
        "available": true,
        "obtained_by": "visible product control",
        "evidence": "private observation reference"
      }
    ]
  },
  "journey": {
    "walked": true,
    "same_actor": true,
    "same_surface": true,
    "evidence": "private journey reference",
    "steps": [
      {
        "page": "Work",
        "control": "Accept Dispatch",
        "surface": "Vendor Portal",
        "observed": true,
        "evidence": "private observation reference"
      }
    ]
  },
  "external": {
    "authorized": true,
    "authorization_evidence": "current user request or approved workflow reference",
    "target": "ticket key or external target",
    "previewed": true
  },
  "terminal": {
    "status": "passed",
    "evidence": "private final-state reference"
  }
}
```

For `claim_e2e_complete`, omit `external`. The remaining evidence is identical.
The `reasoning_effort` field is accepted for auditability but is never consulted
when deciding pass or fail. When `initial_state` is `authenticated`, test-identity
discovery may be omitted. When it is `logged_out`, discovery evidence is required
before requesting user interaction or declaring authentication blocked.

## The walk identity

`authentication.identities` is required when `authentication.required` is
true and the operation is `publish_qa_instructions` or `claim_e2e_complete`:
one block per persona the walk signed in as. A walk as a professional and a
patient declares two blocks, and each one is checked on its own. The single
`authentication.identity` of older packets is still read, as one more block;
the gate checks every block in either place, so a clean first persona never
hides a second. Each block holds a label (an account name or role, never a
credential), the evidence that CI workflows and e2e setup, fixtures and
teardown were searched for it, and `owned_by_automation`. A block for an
identity an automated suite owns also needs:

```json
"identity": {
  "label": "e2e.professional",
  "ownership_checked": true,
  "ownership_evidence": "e2e global setup deletes and recreates its appointment",
  "owned_by_automation": true,
  "owner": "deployed e2e gate (playwright global setup)",
  "unowned_identity_available": false,
  "unowned_identity_evidence": "the seed defines no other professional account",
  "walk_window": {"start": "2026-09-25T15:10:00Z", "end": "2026-09-25T15:40:00Z"},
  "overlap_check": {"checked_at": "2026-09-25T15:41:00Z",
                    "evidence": "CI run list: no e2e run started or finished within the window",
                    "overlapping_runs": 0},
  "disclosure": "walked as e2e.professional, owned by the e2e gate, on the shared preview DB; no run overlapped"
}
```

Failure codes: `IDENTITY_MISSING`, `IDENTITY_LABEL_MISSING`,
`IDENTITY_OWNERSHIP_UNCHECKED`, `IDENTITY_OWNERSHIP_UNKNOWN`,
`IDENTITY_OWNER_MISSING`, `IDENTITY_OWNED_BY_AUTOMATION` (an unowned identity
exists, or the evidence that none does is missing), `WALK_WINDOW_MISSING`,
`OVERLAP_UNCHECKED` (no evidence, or `checked_at` before the walk ended),
`CONCURRENT_AUTOMATION_RUN`, and `IDENTITY_SHARING_UNDISCLOSED`. In qa-sweep
repos, `.qa/config.json` `automation_identities` lists the CI identities, and
the ship gate refuses a packet that declares any of them unowned, in
`identity` or in any `identities` entry.


## Claiming a reached prerequisite blocked


Use `claim_e2e_blocked` only after reaching the intended entry point. The
packet still needs `actor`, `entrypoint`, and `authentication` evidence, but
does not pretend the whole journey was walked. Add:

```json
"blocker": {
  "goal": "finish onboarding with connected data",
  "point": "Connect data screen, Connect Google control",
  "evidence": "current screen snapshot reference",
  "visible_route": "attempted",
  "attempt_evidence": "browser click and resulting screen reference",
  "stop_reason": "the authorized test account was rejected by the provider"
},
"terminal": {
  "status": "blocked",
  "evidence": "provider rejection reference"
}
```

`visible_route` is `attempted`, `none`, or `denied`:

- `attempted`: cite the actual user-facing action and result. Code inspection
  alone cannot fill `attempt_evidence`.
- `none`: cite both inspection of the relevant controls
  (`route_inspection_evidence`) and authorized setup or test-data discovery
  (`setup_discovery_evidence`), plus `stop_reason`.
- `denied`: cite an explicit refusal or permission denial in
  `denial_evidence`. A request that is merely pending is not a terminal blocker.

A broken or missing product control that the user needs is a `FAILED` journey,
not a `BLOCKED` prerequisite. The gate checks evidence shape, not whether a
browser action truly occurred or whether a defect was classified honestly;
compare every reference with the browser trace before reporting the verdict.

## Manual browser login handoff

`request_manual_browser_login` is an interim authorization gate. Before it can
pass, the packet needs actor and entrypoint evidence, authentication with
`required: true`, `initial_state` and current `state` both `logged_out`,
`test_identity_discovery` with `checked: true` and evidence, `attempted: true`
with separate attempt evidence when
an identity was found, and evidence that manual interaction was necessary. The
request operation does not require post-login evidence, a walked journey, or a
terminal `passed` status, and it never authorizes publication or completion.

```json
"manual_login": {
  "instance_id": "page-7f3a",
  "thread_owned": true,
  "reused": true,
  "owned_instances_before": 1,
  "instances_created": 0,
  "instances_exposed_count": 4,
  "necessity_evidence": "why manual interaction was necessary",
  "pre_snapshot": {
    "instance_id": "page-7f3a",
    "url": "https://portal.example.test/login",
    "title": "Sign in",
    "login_control": "Continue with SSO",
    "evidence": "private pre-login snapshot reference"
  },
  "takeover": {
    "authorized": true,
    "evidence": "current user approval reference",
    "shared_window_disclosed": true
  },
  "released": true,
  "post_snapshot": {
    "instance_id": "page-7f3a",
    "authenticated_state_observed": true,
    "evidence": "private post-login snapshot reference"
  }
}
```

Field rules:

- `instance_id` must be nonempty and every snapshot must be bound to the same
  instance; inconsistent ids are rejected.
- `thread_owned` must be true. If `owned_instances_before` is 1, `reused` must
  be true and `instances_created` must be 0. If it is 0, `reused` must be false
  and `instances_created` must be exactly 1. Counts outside 0 or 1 fail.
- `instances_exposed_count` is an integer of at least 1, because a takeover of
  a shared window always exposes at least the target tab.
- `pre_snapshot` requires `url`, `title`, `login_control`, and `evidence`.
- `takeover` requires `authorized: true`, authorization evidence, and
  `shared_window_disclosed: true`.
- For `publish_qa_instructions` and `claim_e2e_complete` packets that include
  `manual_login`, `post_snapshot` (same instance,
  `authenticated_state_observed: true`, evidence) and `released: true` are
  required. The request operation does not check them.

Incident failure codes include `INSTANCE_NOT_BOUND`, `INSTANCE_NOT_OWNED`,
`INSTANCE_NOT_REUSED`, `TAKEOVER_EXPOSURE_UNDISCLOSED`, `PRE_LOGIN_UNVERIFIED`,
`POST_LOGIN_UNVERIFIED`, and `NOT_RELEASED`, plus `INSTANCE_ID_MISMATCH`,
`INSTANCE_COUNT_UNVERIFIED`, `INSTANCE_CREATION_INVALID`,
`EXPOSED_COUNT_INVALID`, `TAKEOVER_UNAUTHORIZED`,
`MANUAL_LOGIN_MISSING`, `MANUAL_INTERACTION_NECESSITY_MISSING`, and
`AUTH_REQUIRED_FOR_MANUAL_LOGIN`, `INITIAL_AUTH_NOT_LOGGED_OUT`,
`AUTH_NOT_LOGGED_OUT`, and `TEST_IDENTITY_ATTEMPT_EVIDENCE_MISSING`.

The packet is self-attested: it verifies required evidence shape and order
only. Runtime instance ownership, takeover authorization, and foreground state
are proven by adapter control-plane and tool evidence, which stay authoritative
over the packet.
