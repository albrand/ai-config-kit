# Card 21 section and source map

## Current homes: section origins

`GLOBAL_AGENTS.md` is the shared kit source. `scripts/typed-decisions-sync.py`
owns the `typed-decisions` marker block. All remaining provider-specific text
in the existing homes is hand-written or historically copied; there is no
generator that keeps those sections in sync today. The proposal renderer makes
that boundary explicit: `hard-rules.md` + the typed block extracted from the
sync script + one provider overlay; the bb home uses `GLOBAL_AGENTS.md` plus
the bb overlay.

| Home | Sections and origin | Duplicate with another file loaded by this agent |
|---|---|---|
| `~/.claude/CLAUDE.md` | Delivery first (kit `GLOBAL_AGENTS.md`, marker synced by local copy); operating framework, default process, always-on behaviors (hand-written); typed decisions (`typed-decisions-sync.py` marker); finish/testing/worktree/host/feature flag/QA/security/Hermes/browser/coordination policies (hand-written copies of shared kit and skills); Claude adapter/provider routing (hand-written). | With bb: delivery-first, scope continuity, email, browser isolation and lifecycle, testing claims, finish-the-job, worktree and host rules, feature flags, Hermes, tokens, typed decisions, security defaults, no AI signatures. |
| `~/.codex/AGENTS.md` | Global Codex workflow, cost routing, default process, OpenCode delegation, board regression, specialized skills, external posting, workflow tracks, worktrees, feature flags, guardrails, browser isolation, Hermes control plane, native surfaces, review scope (hand-written); typed decisions (sync marker); scope continuity, no-AI-signatures, security, token-efficient, testing and finish guards (kit copies/markers). | With bb: delivery-first, scope continuity, typed decisions, email, testing claims, finish-the-job, worktree/host, feature flags, security, tokens, no-AI-signatures. |
| `~/.config/opencode/AGENTS.md` | Delivery first and common agent workflow (kit copy); OpenCode executor/delegation, browser quarantine, Hermes/cmux transport, context GC and adapter boundaries (hand-written); typed decisions (`typed-decisions-sync.py` marker); QA/testing and security (shared-kit copies). | With bb: delivery-first, scope continuity, typed decisions, email, browser isolation/lifecycle, testing claims, finish-the-job, worktree/host, feature flags, security, tokens, no-AI-signatures. |
| `~/.bb/AGENTS.md` | Delivery first, scope continuity, email, browser, worktree/host, testing, feature flags, finish, security, token and typed-decision marker blocks (hand-written copies of kit sources); Hermes review transport, child routing, adapter and browser-login details (hand-written). | This is the shared baseline loaded with Claude and Codex; it duplicates the common policies listed above in each provider row. |
| `~/projects/agent-config-kit/GLOBAL_AGENTS.md` | Kit canonical shared rules; `typed-decisions` is maintained by `scripts/typed-decisions-sync.py`; email/testing/finish/token marker blocks are maintained in this file; other sections are hand-edited. | Duplicated by the bb home and copied into all three provider homes through their kit-backed hard-rules section. |

## Proposed rendered sections and their owners

| Rendered home section | Source | Scope |
|---|---|---|
| Hard prohibitions | `proposals/card21/hard-rules.md` | Compact always-on rules repeated in every provider home. |
| Typed decisions | `scripts/typed-decisions-sync.py` (`GLOBAL_BLOCK`) | Shared synced policy repeated in every provider home. |
| Claude Code adapter | `proposals/card21/overlays/claude.md` | Claude-specific routing, surface, and execution rules. |
| Codex adapter | `proposals/card21/overlays/codex.md` | Codex-specific delegation and board workflow rules. |
| OpenCode adapter | `proposals/card21/overlays/opencode.md` | OpenCode execution, isolation, Hermes, and context-GC rules. |
| bb baseline and adapter | `GLOBAL_AGENTS.md` + `proposals/card21/overlays/bb.md` | Shared bb instructions plus bb-specific routing and transport rules. |

The renderer is `scripts/render-standing-homes.py`; it writes only proposal
artifacts by default. It supports an explicit `--install` mode, which was not
run. `scripts/check-standing-rules.py` validates fixed per-home rule inventories
and strict rendered proposals; it does not decide applicability from candidate
text.
