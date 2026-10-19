---
name: engineering-contracts
description: Use before implementing a feature, changing a shared contract, modifying an LLM-backed output path, or fixing a production defect. Establish outcome, consumers, repository quality rules, and behavior evidence from current sources; load only for implementation and production-fix work, not routine operations.
---

# Engineering contracts

Apply only the contracts relevant to the requested change. Before edits, during implementation, before completion, and after a failure, load the existing skills that own the affected surface. Keep `verify`, `scope-advisor`, `reviewing-with-an-agent`, and applicable release checks in force; this skill does not replace them.

## Outcome — before implementation

Use the real request, requirements, and current behavior to establish: the problem; beneficiary; input; processing; meaningful output; consuming component; observable value; and success evidence. Preserve conflicts and genuine unknowns as questions or assumptions and escalate material ambiguity. Do not invent convenient acceptance criteria. Technical green signals alone do not establish user value.

## Implementation — before and during edits

Read the actual entrypoints and follow the behavior through relevant callers, routes or registrations, UI, services, persistence, downstream consumers, and production readers. Map affected consumers before changing a shared contract and exercise them afterward. Unused code does not complete a feature; an intentional public API is valid when its contract and consumer evidence show that API itself is the requested outcome.

## Quality — before edits and completion

Read the repository's actual CI, type, lint, test, build, architecture, security, and dependency configuration that applies. Preserve every mandatory gate and use the existing `verify` contract when applicable. Select checks from those sources and the owner of the behavior; never invent a weaker standard or treat a green unrelated check as evidence.

## Behavior — before completion

Tie each required outcome to a falsifiable check with realistic inputs, boundaries, and fixtures. Keep the behavior owned by the system under test real; mock only external boundaries. Defined values, truthiness, calls, HTTP 200, success-shaped objects, and coverage counts support a claim but do not prove the requested behavior. When useful, show the check detects the realistic fault or fails before the fix; never weaken assertions or expected outputs. A production regression check must reproduce the original realistic failure boundary and cover affected consumers.

## After failure

Record the source and evidence, actual root cause, why earlier detection missed it, affected contract, recurrence/deduplication key, scoped preventive guidance, and an executable regression when justified, including its result. Keep guidance with the owning skill or source; do not append incident prose indefinitely to global instructions. A native Claude queued report is not healed, and policy text alone does not prove remediation.

For an LLM-backed path, also load [LLM output evidence](references/llm-output-evidence.md). Use the [offline fixture corpus](fixtures/raw/) for representative contract checks when useful; the coordinator oracle is separate and must not be included in blind evaluations.
