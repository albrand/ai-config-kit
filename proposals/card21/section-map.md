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
| `Board-Backed Regression Protection` | Hand-written Codex policy | `overlays/codex.md`; board inventory procedure → `board-access-via-mcp` and `scope-advisor` |
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
| `Board-backed regression protection` | Hand-written board policy | `overlays/opencode.md`; inventory procedure → `board-access-via-mcp` and `scope-advisor` |
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

## `~/projects/agent-config-kit/GLOBAL_AGENTS.md`

| Existing section / block | Origin | Proposed loaded destination |
|---|---|---|
| `Global Agent Instructions` | Kit source | `GLOBAL_AGENTS.md` header |
| `delivery-first` marker / `Delivery first` | Kit source | `GLOBAL_AGENTS.md` → Delivery first; shared prohibitions → `hard-rules.md` |
| `Analyze, plan, and scope` | Kit source | Same section in compact `GLOBAL_AGENTS.md`; details → `scope-advisor` |
| `Cost, models, and agents` | Kit source | Same section in compact `GLOBAL_AGENTS.md`; provider details → routing skills |
| `Directive challenge and decisions` | Kit source | Same section in compact `GLOBAL_AGENTS.md`; semantic procedure → `typed-decisions` |
| `Security and hard prohibitions` | Kit source | `hard-rules.md`; full security gate → security source and quality gate |
| `Worktrees, host, and processes` | Kit source | Same section in compact `GLOBAL_AGENTS.md`; detail → `shared-host-capacity` |
| `Testing and reporting` | Kit source | Same section in compact `GLOBAL_AGENTS.md`; evidence tiers → `meaningful-tests` |
| `ai-config-kit-scope` marker / scope continuity | Kit source | Same section in compact `GLOBAL_AGENTS.md`; `scope-advisor` |
| `email-prohibition` marker | Kit source | `hard-rules.md` |
| `testing-claims` marker | Kit source | `hard-rules.md`; full contract → `meaningful-tests` |
| `finish-the-job` marker | Kit source | `hard-rules.md`; detail → `finish-the-job` |
| `token-efficient-orchestration` marker / section | Kit source | Same section in compact `GLOBAL_AGENTS.md` |
| `typed-decisions` marker / section | `scripts/typed-decisions-sync.py` `GLOBAL_BLOCK` | Same section in compact `GLOBAL_AGENTS.md`; detailed procedure → `typed-decisions` skill |

## Duplicated policy in loaded provider + bb contexts

These topics appear in the provider home and again in `~/.bb/AGENTS.md` today.
The compact proposal retains a standalone copy where the provider must enforce
the rule without assuming the bb baseline was injected. Rule detail moves to
the named owner shown above.

| Repeated policy | Provider source location(s) | bb source location |
|---|---|---|
| Delivery-first and scope continuity | Claude: delivery marker and Operating framework; Codex: delivery marker and Default Process; OpenCode: delivery marker and Core operating principles | delivery marker; ai-config-kit scope continuity |
| Email/compose/send prohibition | Claude: Always-on behaviors; Codex/OpenCode: No Email Without Explicit Approval / Global email guard | Global email guard (OpenCode has copied email marker) |
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
