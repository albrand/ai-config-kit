---
description: Multi-pass, multi-lens security review that reinforces detection through independent blind finder passes and an adversarial refute pass, then reports only confirmed findings. Static by default; owned or authorized targets only.
argument-hint: [path, diff, module, or repo to review]
allowed-tools: Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(rg:*), Bash(grep:*), Bash(ls:*), Bash(find:*), Bash(cat:*)
---

# Adversarial Security Sweep

Run a reinforced security review of the target the user owns or is authorized to
review. Reinforce detection with independent passes; trust only findings that
survive cross-checking.

User input:

`$ARGUMENTS`

## Workflow

1. Load doctrine. If the repo vendors `agent-config-kit`, load
   `SECURITY_AND_PENTEST.md`,
   `skillsets/security-review/references/security-review-contract.md`, and
   `skillsets/security-review/references/supply-chain-iocs.md`. Otherwise apply
   the same doctrine from memory.
2. Scope. Confirm ownership/authorization. Identify the in-scope surface and
   sketch a lightweight STRIDE threat model. Weight build/config and dependency
   files first (supply-chain is the demonstrated real-world failure mode).
3. Run independent finder passes, one lens each, blind to each other:
   access-control, injection/input, secrets/crypto, supply-chain/config,
   ssrf/outbound. Prefer parallel sub-agents (`subagents swarm allowed` posture)
   for the lenses; reconcile on the master thread.
4. Adversarial refute pass. For each candidate, independently try to refute it —
   reachable? already mitigated? false positive? Rate severity on residual
   exposure after existing mitigations. Default to "not confirmed" when
   reachability is uncertain.
5. Loop until dry. Repeat finder passes until a round finds nothing new;
   deduplicate against everything seen.
6. Report using the output contract.

## Guardrails

- Owned or authorized targets only; this command is static/read — for active
  testing use `/pentest-specialist`.
- Rate residual exposure, not raw scanner labels.
- Never report a category clean unless a lens examined it; list skipped surfaces
  under not-examined.
- No offensive/evasive/self-propagating tooling; no real data exfiltration.

## Output

Confirmed findings severity-ordered; refuted/downgraded candidates separately;
lenses run, finder-round count, adversarial-pass status, not-examined surfaces,
and residual risk.
