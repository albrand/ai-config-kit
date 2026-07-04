---
name: adversarial-security-sweep
description: Multi-pass, multi-lens security review that reinforces detection through independent blind finder passes and an adversarial refute pass. Use when reviewing an owned or authorized codebase/change for vulnerabilities with high confidence, or when a change touches auth, data, crypto, external input, dependencies, or build/config files. Static by default; no live target required.
---

# Adversarial Security Sweep

## Trigger

Use this skill when the user wants a thorough security review of code they own
or are authorized to review — "audit security", "find vulnerabilities", "harden
this", "review this change for security" — and false negatives are costly. Also
use it as the security lens of a broader review when a diff touches auth, data,
crypto, external input, dependencies, or build/config files.

This is a static/read workflow. For active testing against a running target,
use `pentest-specialist` and its authorization gate first.

## Doctrine

Load `SECURITY_AND_PENTEST.md`. Single-pass review is unreliable; this skill
reinforces detection with independent passes and only trusts findings that
survive cross-checking (cross-fitting applied to detection — see
`DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md`).

## Workflow

1. Scope. Confirm the target is owned or authorized. Identify the changed or
   in-scope surface (diff, module, or repo) and sketch a lightweight STRIDE
   threat model. Weight build/config and dependency files first — supply-chain
   compromise is the demonstrated real-world failure mode.
2. Run independent finder passes, one per lens, blind to each other:
   - access-control (authz on every boundary, tenant/account isolation, IDOR)
   - injection/input (SQL/NoSQL/command/template/path, escaping)
   - secrets/crypto (secrets in code/logs/config, weak crypto, transport)
   - supply-chain/config (use `references/supply-chain-iocs.md`: appended config
     code, obfuscation markers, `child_process`/`eval` in config, dynamic
     require in ESM, suspicious dependency bumps, zero-width Unicode)
   - ssrf/outbound (user-controlled URLs, metadata endpoints, allow-listing)
   Delegate individual lenses to bounded sub-agents when the harness supports it;
   keep the reconciliation on the master thread.
3. Adversarial refute pass. For each candidate finding, independently try to
   refute it: is it reachable? already mitigated by an existing control? a false
   positive? Credit severity only on the residual exposure after existing
   mitigations. Default to "not confirmed" when reachability is uncertain.
4. Loop until dry. Repeat finder passes until a round surfaces nothing new.
   Deduplicate against everything seen (confirmed and refuted) so refuted items
   do not reappear.
5. Report to `references/security-review-contract.md`.

## Guardrails

- Owned or authorized targets only.
- Do not rate a finding by its raw scanner label; rate residual exposure after
  existing mitigations.
- Do not report a category clean unless a lens examined it; list skipped
  surfaces under not-examined.
- Keep security judgment on the strongest reasoning path; delegate only bounded,
  verifiable lens work.
- No offensive, evasive, or self-propagating tooling; no real data exfiltration.

## Output

Return the run-level and per-finding fields from the output contract: confirmed
findings severity-ordered, refuted/downgraded candidates separately, lenses run,
finder-round count, adversarial-pass status, not-examined surfaces, and residual
risk.
