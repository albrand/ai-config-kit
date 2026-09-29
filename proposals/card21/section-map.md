# Card 21 section and source map

This inventory names every Markdown heading and managed marker block in each
unchanged live home. “Hand-written” includes copied text without an active
generator. Destination names refer to the proposed loaded source files; detail
moved out of always-on context is named explicitly.

## `~/.claude/CLAUDE.md`

| Existing section / block | Current origin | Proposed loaded destination |
|---|---|---|
| `CLAUDE.md (user-level)` | Hand-written provider header | `overlays/claude.md` header |
| `delivery-first` marker block | Kit `GLOBAL_AGENTS.md`, copied into home | `GLOBAL_AGENTS.md` → Delivery first; `hard-rules.md`; `overlays/claude.md` |
| `Operating framework` | Hand-written Claude adapter | `overlays/claude.md`; scope detail → `scope-advisor` |
| `Default process` | Hand-written Claude workflow | `overlays/claude.md`; board, tests, reviews, and orchestration detail → their named skills |
| `Always-on behaviors` | Hand-written summary plus copied common rules | `hard-rules.md`; `overlays/claude.md`; named skills for browser, tests, capacity, and delivery |
| `ai-config-kit-scope` marker block / `ai-config-kit scope continuity` | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → scope continuity; `scope-advisor` |
| `token-efficient-orchestration` marker block / `Token-efficient orchestration (all providers)` | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → Token-efficient orchestration |
| `typed-decisions` marker block / typed decisions section | `scripts/typed-decisions-sync.py` `GLOBAL_BLOCK` | Same synced block in the rendered Claude home; procedure → `typed-decisions` skill |

## `~/.codex/AGENTS.md`

| Existing section / block | Current origin | Proposed loaded destination |
|---|---|---|
| `Global Codex Workflow` | Hand-written Codex header | `overlays/codex.md` header |
| `delivery-first` marker block | Kit `GLOBAL_AGENTS.md`, copied into home | `GLOBAL_AGENTS.md` → Delivery first; `hard-rules.md`; `overlays/codex.md` |
| `Global Cost Routing Directive` | Hand-written Codex policy | `overlays/codex.md`; routing detail → `token-economics` and provider skills |
| `Default Process` | Hand-written Codex workflow | `overlays/codex.md`; scope, orchestration, skills, and testing detail → named skills |
| `opencode Delegation (mandatory standing authorization)` | Hand-written Codex delegation contract | `overlays/codex.md`; execution procedure → `delegating-to-glm` / adaptive-model-orchestrator |
| `GLM-5.3 routing` | Hand-written delegation subsection | `overlays/codex.md`; provider details → `delegating-to-glm` |
| `opencode is a trusted, pre-authorized channel (private-context exception)` | Hand-written delegation subsection | `overlays/codex.md`; bounded execution → adaptive-model-orchestrator |
| `Board-Backed Regression Protection` | Hand-written Codex policy | `overlays/codex.md` retains the universal trigger, authoritative-board blocker, required inventory fields, adjacent-ticket detail reads, and regression/traceability blockers; `board-access-via-mcp` and `scope-advisor` add access/scope procedure only |
| `Specialized Workflow Skills` | Hand-written skill router | `overlays/codex.md`; procedures remain in their named skills |
| `External Posting Content` | Hand-written policy | `hard-rules.md`; QA instructions → `verified-qa-e2e` |
| `Workflow Tracks, Breakpoints, Quality Convergence` | Hand-written process policy | `GLOBAL_AGENTS.md` → Analyze, plan, and scope / Testing and reporting; detail → `scope-advisor` and `meaningful-tests` |
| `Worktree Lifecycle` | Hand-written copy of shared host policy | `hard-rules.md`; lifecycle/capacity detail → `shared-host-capacity` |
| `No Feature Flags Without An Explicit Ask` | Hand-written copy | `hard-rules.md`; invariant remains in every provider home |
| `Guardrails` | Hand-written grouping heading | No standalone rule; following email, browser, and control-plane sections map below |
| `No Email Without Explicit Approval` | Hand-written copy | `hard-rules.md`; email path verification detail stays in that compact rule |
| `Browser Surface Isolation` | Hand-written copy | `hard-rules.md`; interactive workflow → `isolated-browser` and `verified-qa-e2e` |
| `Independent Hermes Control Plane` | Hand-written Codex adapter policy | `overlays/codex.md`; transport details → approved Hermes broker instructions |
| `Native Agent Surface Discovery` | Hand-written adapter policy | `overlays/codex.md`; lifecycle and lease details → native-agent-surface skill |
| `Test Ownership And Re-Review Scope` | Hand-written review policy | `GLOBAL_AGENTS.md` → Testing and reporting; review procedure → `meaningful-tests` / PR-review skill |
| `ai-config-kit-scope` marker block / `ai-config-kit scope continuity` | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → scope continuity; `scope-advisor` |
| `no-ai-signatures` marker block | Kit `GLOBAL_AGENTS.md` | `hard-rules.md` |
| `security-first-defaults` marker block | Kit security policy copy | `hard-rules.md`; full gate → `SECURITY_AND_PENTEST.md` and `QUALITY_GATES.md` |
| `token-efficient-orchestration` marker block / section | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → Token-efficient orchestration |
| `typed-decisions` marker block / typed decisions section | `scripts/typed-decisions-sync.py` `GLOBAL_BLOCK` | Same synced block in the rendered Codex home; procedure → `typed-decisions` skill |
| `Global testing-claim guard` | Hand-written copy of shared testing rule | `hard-rules.md`; evidence tiers → `meaningful-tests` |
| `Global finish-the-job guard` | Hand-written copy of shared delivery rule | `GLOBAL_AGENTS.md` → Delivery first; follow-through → `finish-the-job` |

## `~/.config/opencode/AGENTS.md`

| Existing section / block | Current origin | Proposed loaded destination |
|---|---|---|
| `Global opencode Agent Instructions` | Hand-written OpenCode header | `overlays/opencode.md` header |
| `delivery-first` marker block | Kit `GLOBAL_AGENTS.md`, copied into home | `GLOBAL_AGENTS.md` → Delivery first; `hard-rules.md`; `overlays/opencode.md` |
| `Delegated fast path (performance-critical)` | Hand-written OpenCode execution policy | `overlays/opencode.md`; execution contract → adaptive-model-orchestrator |
| `Framework adoption` | Hand-written OpenCode policy | `overlays/opencode.md`; adoption detail → repository skills and `scope-advisor` |
| `Core operating principles` | Hand-written OpenCode workflow | `overlays/opencode.md`; testing and scope detail → named skills |
| `Routing tiers (opencode-adapted)` | Hand-written routing policy | `overlays/opencode.md`; routing detail → `delegating-to-glm` |
| `GLM-5.3 route` | Hand-written routing subsection | `overlays/opencode.md`; provider details → `delegating-to-glm` |
| `Workspace/topic input isolation` | Hand-written adapter safety policy | `overlays/opencode.md`; lease/control-plane procedure → native-agent-surface |
| `Skills (on-demand, progressively loaded)` | Hand-written skill routing | `overlays/opencode.md`; procedures remain in named skills |
| `Source-of-truth order` | Hand-written operating policy | `overlays/opencode.md` |
| `Board-backed regression protection` | Hand-written board policy | `overlays/opencode.md` retains the universal trigger, authoritative-board blocker, required inventory fields, adjacent-ticket detail reads, and regression/traceability blockers; `board-access-via-mcp` and `scope-advisor` add access/scope procedure only |
| `Workflow tracks, breakpoints, quality convergence` | Hand-written workflow policy | `GLOBAL_AGENTS.md` → Analyze, plan, and scope; detail → `scope-advisor` |
| `Validation truthfulness and completion standard` | Hand-written testing policy | `hard-rules.md`; full contract → `meaningful-tests` |
| `Running as a delegated executor (invoked by Codex/Claude)` | Hand-written executor contract | `overlays/opencode.md`; execution procedure → adaptive-model-orchestrator |
| `Always report changes (always-on)` | Hand-written completion policy | `GLOBAL_AGENTS.md` → Testing and reporting; `finish-the-job` |
| `Guardrails` | Hand-written grouping heading | No standalone rule; following browser, Hermes, email, worktree, and flag sections map below |
| `Browser Surface Isolation` | Hand-written copy | `hard-rules.md`; workflow → `isolated-browser` and `verified-qa-e2e` |
| `cmux + Hermes Control Plane` | Hand-written OpenCode transport policy | `overlays/opencode.md`; transport detail → approved Hermes broker instructions |
| `Native Agent Surfaces` | Hand-written adapter policy | `overlays/opencode.md`; lifecycle and lease details → native-agent-surface skill |
| Active-session input safeguards (within `Native Agent Surfaces`) | Hand-written adapter safety policy | `GLOBAL_AGENTS.md` compact hard-rule pointer; provider hard-rules retain exact authority/ownership prohibitions; procedure → `native-agent-surface` and `scripts/session-input-guard.py` |
| `Test Ownership And Re-Review Scope` | Hand-written review policy | `GLOBAL_AGENTS.md` → Testing and reporting; review procedure → `meaningful-tests` / PR-review skill |
| `global-email-guard` marker block / `Global email guard` | Kit rule copied into home | `hard-rules.md` |
| `worktree-lifecycle` marker block | Kit rule copied into home | `hard-rules.md`; detail → `shared-host-capacity` |
| `feature-flag-guard` marker block | Kit rule copied into home | `hard-rules.md` |
| `ai-config-kit-scope` marker block / scope continuity | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → scope continuity; `scope-advisor` |
| `no-ai-signatures` marker block | Kit `GLOBAL_AGENTS.md` | `hard-rules.md` |
| `security-first-defaults` marker block | Kit security policy copy | `hard-rules.md`; full gate → `SECURITY_AND_PENTEST.md` and `QUALITY_GATES.md` |
| `token-efficient-orchestration` marker block / section | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → Token-efficient orchestration |
| `typed-decisions` marker block / section | `scripts/typed-decisions-sync.py` `GLOBAL_BLOCK` | Same synced block in the rendered OpenCode home; procedure → `typed-decisions` skill |
| `Global testing-claim guard` | Kit rule copied into home | `hard-rules.md`; evidence tiers → `meaningful-tests` |
| `Global finish-the-job guard` | Kit rule copied into home | `GLOBAL_AGENTS.md` → Delivery first; follow-through → `finish-the-job` |

## `~/.bb/AGENTS.md`

| Existing section / block | Current origin | Proposed loaded destination |
|---|---|---|
| `delivery-first` marker block | Kit `GLOBAL_AGENTS.md` copied into bb home | `GLOBAL_AGENTS.md` → Delivery first; `hard-rules.md`; bb overlay |
| `Global email guard` | Kit shared rule copied into bb home | `hard-rules.md` |
| `Global bb browser-login handoff guard` | Hand-written bb adapter and shared browser rules | `hard-rules.md`; workflow → `isolated-browser` and `verified-qa-e2e`; login-specific instructions → `overlays/bb.md` |
| `Global worktree lifecycle guard` | Kit shared host policy copy | `GLOBAL_AGENTS.md` → Worktrees, host, and processes; `shared-host-capacity` |
| `Global testing-claim guard` | Kit shared testing policy copy | `hard-rules.md`; evidence tiers → `meaningful-tests` |
| `Global finish-the-job guard` | Kit shared delivery policy copy | `GLOBAL_AGENTS.md` → Delivery first; `finish-the-job` |
| `Global feature-flag guard` | Kit shared policy copy | `hard-rules.md` |
| `ai-config-kit-scope` marker block / scope continuity | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → scope continuity; `scope-advisor` |
| `browser-surface-isolation` marker block | Kit browser policy copy | `hard-rules.md`; workflow → `isolated-browser` |
| `no-ai-signatures` marker block | Kit `GLOBAL_AGENTS.md` | `hard-rules.md` |
| `security-first-defaults` marker block | Kit security policy copy | `hard-rules.md`; full gate → security source and quality gate |
| `token-efficient-orchestration` marker block / section | Kit `GLOBAL_AGENTS.md` | `GLOBAL_AGENTS.md` → Token-efficient orchestration |
| `typed-decisions` marker block / section | `scripts/typed-decisions-sync.py` `GLOBAL_BLOCK` | Same synced block in rendered bb home; procedure → `typed-decisions` skill |
| `Global Hermes review transport` | Hand-written bb/Hermes adapter rules | `overlays/bb.md`; Codex/OpenCode transport additions → their respective overlays |
| `Global child-agent routing (subscription-aware)` | Hand-written bb routing policy | `overlays/bb.md`; route details → provider routing skill |

## Kit source section reconciliation

The baseline side below is the complete heading and managed-block inventory
from the hash-confirmed `GLOBAL_AGENTS.md` at `b6775918a3f749bc643c76094aee8cedac5dbb11`,
not a reconstruction from the compact candidate. Baseline sections originate
in that hand-written kit file unless the row names the sync script. Detailed
procedures move only to the named existing skill or source document.

| Original baseline heading/block | Source origin | Retained compact rule | Detail and destination |
|---|---|---|---|
| `Global Agent Instructions` and opening paragraph | Hand-written in baseline kit file | Header defines a provider-neutral baseline; provider homes remain adapter-only and repeat hard prohibitions | — |
| `delivery-first` marker block | Hand-written in kit file; copied into homes | `Delivery first` retains one-ticket/one-PR, reproduce, close batch inventory, one final workflow re-walk, focused checks, named-Hermes-defect stop, safety-hook block, and pre-review packet plus reusable defect checks | End-to-end delivery → `finish-the-job`; Pallium PR workflow → `pallium-ship-workflow` |
| `Core Operating Principles` §1–4 | Hand-written in kit file | `Analyze, plan, and scope` retains request/source inspection, non-code goal/deliverable/assumption/risk/output framing, proportionate plan, connected-surface tracing, reproduce/evidence, and explicit uncertainty | Scope procedure → `scope-advisor`; evidence limits → `meaningful-tests` |
| `Board-Backed Regression Protection` | Hand-written in kit file | `Analyze, plan, and scope` retains the universal trigger, board-access blocker, full inventory fields, adjacent/completed-ticket detail reads, and regression/traceability blockers | Board access procedure and scope advice → `board-access-via-mcp` and `scope-advisor` |
| `Security-First Defaults` introduction and security gate | Hand-written in kit file | `Security and hard prohibitions` retains trigger domains and mandatory `SECURITY_AND_PENTEST.md` / `QUALITY_GATES.md` gate | Detailed gate → those two sources |
| `Interactive browser and tab hygiene` | Hand-written in kit file | Candidate hard rules retain isolated bb browser, page ownership, enumeration, non-creating lifecycle calls, and no personal browser | Browser workflow → `isolated-browser`; adapter-specific controls → `orca-browser-safety` |
| `Manual login handoff in a shared browser window` | Hand-written in kit file | Candidate hard rules retain one owned instance, no focus-multiplying tabs, truthful shared-window claims, no credential handling, same-instance auth verification, and stop on challenge/decline/contradiction | Login and evidence gates → `isolated-browser` and `verified-qa-e2e` |
| `Security-First Defaults` supply chain, residualization, high-stakes review, authorized defense | Hand-written in kit file | Candidate retains supply-chain/build-config priority, residual exposure, authorized defensive-only activity, no offensive tooling, and multi-pass high-stakes review | Full method → security docs and `adversarial-security-sweep` |
| `Security-First Defaults` Hermes/native surface/session-start clauses | Hand-written in kit file | Candidate retains no reverse SSH/listeners/broad env forwarding, capability-secret ban, preference-gated native discovery, exact lease/attestation gate, and safe session resume | Transport → `CMUX_HERMES_ORCHESTRATION.md`; native surfaces and health → `NATIVE_AGENT_SURFACES.md`, `SESSION_START_HEALTH.md`, and `claude-session-hook-doctor.py` |
| `Collaboration Defaults` | Hand-written in kit file | Candidate now retains directness, findings/verdict-first responses, paste-ready prompts, source-conflict questions, and durable workflow fixes; no-AI-signature rule remains explicit | PR-body limits and concrete-value requirement remain inline in `Analyze, plan, and scope` |
| `Scope Boundaries` | Hand-written in kit file | Candidate now states global-vs-repository ownership and retains scope-advisor trigger/authority | Full scope protocol → `scope-advisor` and `SCOPE_DISCIPLINE.md` |
| `Closed-Scope Protection` | Hand-written in kit file | Candidate now explicitly keeps credentials, private URLs, personal/account identifiers, non-public roadmap and organization facts out of global context | — |
| `Completion Report Standard` | Hand-written in kit file | Candidate now retains implementation/review closeout fields, evidence, unvalidated work, residual risk/next step, and proposed/implemented/installed/verified distinctions | Test and capability procedure → `meaningful-tests` and `finish-the-job` |
| Worktree lifecycle / shared-host-capacity blocks | Hand-written in kit file | Candidate retains own-worktree removal and own-live-bb-environment exception, dirty/unowned protections, detached-HEAD lifetime, one-writer, dependency clone, CPU, and disk rules | Full lifecycle and host procedure → `shared-host-capacity` |
| No-feature-flags block | Hand-written in kit file | Candidate provider proposals and `hard-rules.md` retain all prohibitions, exceptions, removal ticket/default-on date, and regression assertion | — |
| `ai-config-kit-scope` marker block | Hand-written in kit file; copied into homes | Candidate retains original request/revision, authorization, scope continuity, and closeout distinctions | Advisor protocol → `scope-advisor` and `SCOPE_DISCIPLINE.md` |
| `email-prohibition` marker block | Hand-written in kit file; copied into homes | `hard-rules.md` and all applicable provider homes retain per-message approval, every compose/send route, safe verification, and open-compose handling | — |
| `testing-claims` marker block | Hand-written in kit file; copied into homes | Candidate retains persona/target/goals/verdict, NOT RUN, full-workflow PASS, failure/blocked distinction, and no observation-as-verdict | Full contract and evidence ceilings → `meaningful-tests` |
| `finish-the-job` marker, coordination rule, and bb-app prohibition | Hand-written in kit file; copied into homes | Candidate retains follow-through, capability-check-before-blocker, shared-consumer check, when-to-coordinate rules, and never quit/kill/replace bb | Full follow-through/coordination → `finish-the-job` and `orchestration` |
| `token-efficient-orchestration` marker block | Hand-written in kit file; copied into homes | All six target-state, measurement-return, effort, mutation-ledger, verbatim-head, and retry-cost rules remain in compact candidate | Canonical expansion → `TOKEN_EFFICIENT_ORCHESTRATION.md` |
| `typed-decisions` marker block | `scripts/typed-decisions-sync.py` `GLOBAL_BLOCK` | Synced block retains answer-space, atomic judgments, confidence evidence, ledger resolution, Jev boundaries | Full procedure → `typed-decisions` skill |

The compact candidate itself is sourced from `GLOBAL_AGENTS.md`; the typed
decisions block is the sole section actively regenerated by
`scripts/typed-decisions-sync.py`. `scripts/render-standing-homes.py` reads the
kit source and that sync block, then writes proposal files only unless
`--install` is explicitly passed. The baseline-to-candidate preservation
comparison uses every checker regex matching the archived original blob; each
matched hard rule also has a mutation test that removes its matching candidate
text and requires the checker to report it missing.

## Duplicated policy in loaded provider + bb contexts

These topics appear in the provider home and again in `~/.bb/AGENTS.md` today.
The compact proposal retains a standalone copy where the provider must enforce
the rule without assuming the bb baseline was injected. Rule detail moves to
the named owner shown above.

| Repeated policy | Provider source location(s) | bb source location |
|---|---|---|
| Delivery-first and scope continuity | Claude: delivery marker and Operating framework; Codex: delivery marker and Default Process; OpenCode: delivery marker and Core operating principles | delivery marker; ai-config-kit scope continuity |
| Email/compose/send prohibition | Claude: Always-on behaviors; Codex/OpenCode: No Email Without Explicit Approval / Global email guard | Global email guard (OpenCode has copied email marker) |
| Never quit/kill/replace the running bb app or move/delete/overwrite its installed bundle | Claude: Always-on behaviors; Codex: delivery-first hard prohibitions; OpenCode: delivery-first hard prohibitions | Global finish-the-job guard |
| Isolated browser and login handling | Claude: Always-on behaviors; Codex: Browser Surface Isolation; OpenCode: Browser Surface Isolation | Global bb browser-login handoff guard; browser-surface-isolation marker |
| Worktree ownership and removal | Claude: Always-on behaviors; Codex: Worktree Lifecycle; OpenCode: worktree-lifecycle marker | Global worktree lifecycle guard |
| Shared-host limits, dependency handling, low-disk stop | Claude: Always-on behaviors; Codex: Worktree Lifecycle; OpenCode: worktree-lifecycle marker | Global worktree lifecycle guard |
| Automation single-flight and push-is-not-completion | Claude: Always-on behaviors; Codex: Worktree Lifecycle; OpenCode: worktree-lifecycle marker | Global worktree lifecycle guard |
| Testing claims and workflow verdicts | Claude: Always-on behaviors; Codex/OpenCode: Global testing-claim guard | Global testing-claim guard |
| Finish-the-job follow-through | Claude: Always-on behaviors; Codex/OpenCode: Global finish-the-job guard | Global finish-the-job guard |
| Feature-flag prohibition | Claude: Always-on behaviors; Codex: No Feature Flags Without An Explicit Ask; OpenCode: feature-flag-guard marker | Global feature-flag guard |
| No AI signatures | Claude: Always-on behaviors; Codex/OpenCode: no-ai-signatures marker | no-ai-signatures marker |
| Security-first defaults | Claude: Always-on behaviors; Codex/OpenCode: security-first-defaults marker | security-first-defaults marker |
| Token-efficient orchestration | token-efficient-orchestration marker in each provider | token-efficient-orchestration marker |
| Typed decisions | typed-decisions marker in each provider | typed-decisions marker |
| Hermes transport / review boundary | Codex: Independent Hermes Control Plane; OpenCode: cmux + Hermes Control Plane | Global Hermes review transport |
| Active-session input authorization and write ownership | Claude/Codex/OpenCode native-agent-surface policy; loaded from `native-agent-surface` skill and its guard | No active-session clause in bb baseline; standalone providers preserve the contract and skill trigger |

The renderer is `scripts/render-standing-homes.py`; it writes proposals only by
default. Its `--install` mode was not run. `scripts/check-standing-rules.py`
validates fixed per-home rule inventories. At a native path it accepts only
exact SHA-256 fingerprints for an unchanged legacy home or the exact rendered
install artifact; edited or unknown content fails closed. Rendered paths use
strict proposal inventories. Provider proposals carry the hard prohibitions
themselves because an agent may load a provider file without the bb baseline.
