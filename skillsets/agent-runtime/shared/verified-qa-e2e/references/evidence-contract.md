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
    }
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
