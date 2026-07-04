# Security Review Skillset

This skillset turns the defensive security doctrine into executable Codex and
Claude Code workflows. It is white-hat by construction: find → validate → fix →
regress on targets the operator owns or is authorized to test.

Use it when the user asks to review security, harden an app, audit for
vulnerabilities, threat-model a change, check supply-chain/dependency risk, or
run a pentest against an owned or authorized target.

## Entry Points

- Codex adversarial sweep: `skillsets/security-review/codex/adversarial-security-sweep/SKILL.md`
- Codex pentest specialist: `skillsets/security-review/codex/pentest-specialist/SKILL.md`
- Claude Code adversarial sweep: `skillsets/security-review/claude/commands/adversarial-security-sweep.md`
- Claude Code pentest specialist: `skillsets/security-review/claude/commands/pentest-specialist.md`
- Shared doctrine: `SECURITY_AND_PENTEST.md`
- Output contract: `skillsets/security-review/references/security-review-contract.md`
- Supply-chain IoCs and CI guard: `skillsets/security-review/references/supply-chain-iocs.md`

## Two Workflows, One Doctrine

- `adversarial-security-sweep` — multi-pass, multi-lens review that reinforces
  detection. Runs several independent, blind finder passes (different lenses),
  then an adversarial refute pass, loops until dry, and reports only confirmed
  findings. This is the "multiple sessions to reinforce cybersecurity violation
  detection" mechanism. Static by default; no live target required.
- `pentest-specialist` — authorization-gated dynamic testing against an owned or
  authorized target, following the vulnerability lifecycle to a fix and a
  regression test. Requires the authorization gate before any active testing.

Both enforce the same guardrails from `SECURITY_AND_PENTEST.md`: authorized
targets only, prove exploitability after existing mitigations, minimal
proof-of-concept, no offensive/evasive/self-propagating tooling, security
judgment stays on the strongest reasoning path.

## Relationship To Built-In Review

These complement, not replace, a general PR/diff review (`skillsets/pr-review/`)
and any host-provided `security-review` command. Route here when the request is
specifically about finding and fixing vulnerabilities with multi-pass
reinforcement, or when a change touches auth, data, crypto, external input,
dependencies, or build/config files.

## Safety

- Establish authorization before active testing; otherwise stay static.
- Weight supply-chain / build-config compromise first — it is the operator's
  demonstrated real-world failure mode (see the grounding incident in the
  doctrine).
- Keep proof-of-concept minimal and convert it into a fix plus regression test.
- Do not clone offensive tooling or evasion techniques into repos.
