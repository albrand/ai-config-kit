# Security Review Output Contract

Both security-review workflows return findings in this shape. It exists so a
multi-pass run can be deduplicated, verified, and reported consistently.

## Per-Finding Fields

- `id`: stable slug (e.g. `authz-order-endpoint`).
- `title`: one sentence.
- `category`: OWASP/ASVS or supply-chain class.
- `lens`: which pass found it (access-control, injection, secrets-crypto,
  supply-chain-config, ssrf-outbound, other).
- `location`: `path:line` or component.
- `severity`: critical / high / medium / low / info — rated on **residual**
  exposure after existing mitigations.
- `reachability`: how it is reached, and what existing control was accounted for
  before crediting the finding.
- `validation`: proof it is real (reproducer, decoded payload, failing test) or
  `static-only` with why.
- `verdict`: `confirmed` or `refuted` after the adversarial pass.
- `refute_reason`: for refuted/downgraded findings, why (not reachable, already
  mitigated, false positive).
- `fix`: boundary-correct remediation.
- `regression`: test or CI guard that fails if it returns.

## Run-Level Fields

- `target` and `authorization_basis`.
- `lenses_run` and `finder_rounds` (loop-until-dry count).
- `adversarial_pass`: yes/no.
- `not_examined`: surfaces skipped and why.
- `residual_risk`.

## Reporting Rules

- Report `confirmed` findings severity-ordered; list `refuted`/downgraded
  separately so they are not silently dropped and do not reappear next round.
- Never report a category clean unless a lens actually examined it; list it under
  `not_examined` instead.
- Distinguish confirmed / refuted / static-only / not-examined. Do not imply a
  skipped surface passed.
