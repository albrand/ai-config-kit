# Templates

Copy and adapt these templates locally.

## Task Plan

```md
Objective:
- <what we are solving>

Scope:
- <included>

Non-goals:
- <excluded>

Impacted surface:
- <files/modules/systems>

Approach:
- <steps>

Directive challenge:
- <independent advisor or self-critique used, assumptions challenged, and adopted/rejected changes>

Validation:
- <checks>

Rollback/fallback:
- <how to revert or contain>
```

## Harness Routing Plan

```md
Goal:
- <user outcome>

Constraints:
- <instructions, source-of-truth rules, platform limits>

Risks:
- <architecture, security, data, validation, or scope risks>

Directive challenge:
- <advisor route or single-agent fallback>
- <authorization sentence included for directive/planning/architecture/challenge briefs: yes|no|not applicable>
- <memory/journal/cached/project-pattern assumptions challenged>

Subtasks:
- <unit of work> -> <master/local/small/medium/large/delegated role> because <reason>

Cache decision:
- <use/bypass/not available> because <source and freshness reason>

Escalation triggers:
- <when to stop and return to strongest reasoning path>

Validation:
- <checks each routed unit must run or produce>
```

## Harness Capability Record

```md
Harness capabilities:
- File read access: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- File edit access: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Shell or command execution: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Validation execution: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Sub-agents or delegation: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Cross-agent counterpart access: <available|limited|blocked|unavailable|unknown> - <tool/auth/capture evidence and fallback>
- Model routing: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Cache or memory: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- MCP or external integration routing: <available|limited|blocked|unavailable|unknown> - <repo/folder/workflow allow-list evidence and fallback>
- Network or external tools: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Browser or UI verification: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Persistent journals: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
```

## Framework Readiness Report

```md
Framework readiness:
- Maturity level: <Starter|Usable|Harnessed|Durable|Verified>
- Files present: <passed|failed> - <gaps or "None identified">
- Adapter path: <tool and path>
- Harness capabilities: <summary>
- Cross-agent counterpart: <available|limited|blocked|unavailable|not useful and fallback>
- Journaling: <required|optional|disabled and path>
- Required validation: <commands or "not defined">
- Closed-scope scan: <passed|failed|not run>
- First-session check: <passed|failed|not run>
- Skill library index: <fresh|stale|missing|not applicable|blocked> - <counts or blocker>
- Archive updated: <yes|no|not applicable>

Gaps:
- <gap or "None identified">

Next action:
- <smallest useful next step>
```

## Skill Library Index Report

```md
Skill library index:
- CODEX_HOME: <path or "not detected">
- Router installed: <yes|no|blocked>
- Refresh command: <passed|failed|blocked|not run>
- Check command: <passed|failed|blocked|not run>
- Total skills: <number or unknown>
- Implicit skills: <number or unknown>
- Explicit-only skills: <number or unknown>
- Policy changes: <number or "not run">
- Generated files:
  - skill-index.json: <present|missing|blocked>
  - skill-index.md: <present|missing|blocked>
  - applied-policy-summary.json: <present|missing|blocked>
- Access rule: <explicit-only skills remain router-accessible|exception>
- Residual risk: <risk or "None identified">
```

## Cross-Agent Communication Plan

```md
Cross-agent communication plan:
- Coordinator: <tool/model and responsibilities>
- Counterpart: <tool/model and responsibilities, or "unavailable">
- Goal: <shared outcome>
- Authorization: <include for directive/planning/architecture/challenge briefs>
- Source of truth:
  - <files/issues/designs/logs>
- Work split:
  - <unit> -> <owner> -> <expected evidence>
- Context package:
  - <exact paths, snippets, commands, or constraints passed>
- Output contract:
  - <format, max length, required evidence, forbidden content>
- Budget:
  - <token, dollar, time, or turn cap>
- Execution boundary:
  - <sandboxed|outside-sandbox approved|outside-sandbox unavailable>
- Stop conditions:
  - <auth failure, ambiguous architecture, validation failure, scope expansion>
- Fallback:
  - <single-agent path if counterpart is unavailable>
```

## Quality Convergence Plan

```md
Quality convergence:
- Workflow track: <quick|standard|big-change|recovery|review>
- Target: <score or pass criteria>
- Max iterations: <number>
- Dimensions:
  - Requirements alignment: <target and evidence>
  - Functional correctness: <target and evidence>
  - Test strength: <target and evidence>
  - Maintainability: <target and evidence>
  - Security/data boundary: <target and evidence>
- Breakpoints:
  - <decision gate or "None">
- Stop conditions:
  - <target met|blocked|plateau|scope decision|required approval>
```

## Quality Convergence Report

```md
Quality convergence result:
- Target: <score or pass criteria>
- Iterations run: <number>
- Current readiness: <score or status>
- Evidence:
  - <check/output/behavior>
- Failed or blocked:
  - <gap or "None">
- Stop reason: <target met|blocked|plateau|scope decision|required approval>
- Next step: <smallest useful next action>
```

## Workflow Resume Packet

```md
Workflow state:
- Run or task: <identifier>
- Phase: <current phase>
- Last completed step: <step and evidence>
- Pending breakpoint: <decision needed or "None">
- Blockers: <blockers or "None">
- Next exact step: <resume action>
- Validation state: <passed/failed/blocked/skipped/not run summary>
```

## Interactive Review Kickoff

```md
Review mode question:
- 1/ BIG CHANGE: interactive section-by-section review with at most four top
  issues per section: Architecture, Code Quality, Tests, Performance.
- 2/ SMALL CHANGE: interactive review with exactly one question per review
  section.

Recommended:
- <1/ BIG CHANGE or 2/ SMALL CHANGE and why>

Decision prompt:
- Use the platform structured question tool when available. If the tool is
  named AskUserQuestion, each option should include both issue number and option
  letter, with the recommended option first.
```

## Source-Of-Truth Conflict Question

```md
I found a conflict before implementation:

- Source A says: <summary>
- Source B says: <summary>
- Affected area: <path or workflow>

Which source should control this change?
```

## Session Journal Entry

```md
## <timestamp> - <action|decision|issue|result>

<short factual note>

Files:
- <path>

Validation:
- <command>: <status>
```

## Debugging Report

```md
Symptom:
- <exact failure>

Reproduction:
- <command/steps>

Expected:
- <expected behavior>

Actual:
- <actual behavior>

Root cause:
- <confirmed cause or leading hypothesis>

Fix:
- <smallest safe fix>

Validation:
- <command>: <status>

Residual risk:
- <risk or "None identified">
```

## Validation Report

```md
Validation:
- <command>: passed
- <command>: failed - <reason>
- <command>: blocked - <blocker>
- <command>: skipped - <why>
- <command>: not run - <why>

Direct behavior checked:
- <what proves the requested outcome>

Residual risk:
- <remaining gap or "None identified">
```

## Completion Report

```md
Changed:
- <files/areas>

Verified:
- <commands and outcomes>

Not verified:
- <checks not run and why>

Self-review:
- <issues found/fixed or no additional findings>

Residual risk:
- <risk or "None identified">
```

## Review Finding

```md
1. <path>:<line>
<what is wrong and why it matters>

Recommendation:
- <specific fix>
```

## Ecosystem Terraform Plan

```md
Objective:
- <roadmap|tech|hardening outcome>

Mode:
- <import existing|transform existing|create new|connect only|local bootstrap|CI/review bootstrap|infrastructure bootstrap|legacy reconcile|assessment only>

Sources to inspect:
- <docs/repos/designs/boards/PRs/cloud/deployments/tickets>

Questions:
- <question or "None before discovery">

Capabilities:
- <repo/tracker/design/cloud/deploy/sub-agent status and approval gates>

Artifacts:
- <roadmap/docs/tickets/QA matrix/platform plan>

Validation:
- <reference scan, traceability check, ticket contract check, QA gate, external mutation confirmation>

Stop conditions:
- <missing access, conflicting sources, mutation approval required, scope expansion>
```

## Business Logic QA Matrix

```md
| Requirement | Source | Expected behavior | Test or QA evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| <requirement> | <ticket/doc/design> | <observable behavior> | <test/check/manual QA> | <owner or unknown> | <ready|blocked|gap> |
```

## Technical Quality Layer Matrix

```md
| Layer | Current evidence | Status | Scaffold or ticket | Blocking behavior | Owner |
| --- | --- | --- | --- | --- | --- |
| Local validation | <commands/files> | <present|needs update|missing|not applicable|blocked> | <file/ticket/action> | <blocking|required|advisory|N/A> | <owner or unknown> |
| CI/CD validation | <workflows/checks> | <present|needs update|missing|not applicable|blocked> | <file/ticket/action> | <blocking|required|advisory|N/A> | <owner or unknown> |
| PR validation | <template/rules/checks> | <present|needs update|missing|not applicable|blocked> | <file/ticket/action> | <blocking|required|advisory|N/A> | <owner or unknown> |
| Security validation | <scans/policies/tests> | <present|needs update|missing|not applicable|blocked> | <file/ticket/action> | <blocking|required|advisory|N/A> | <owner or unknown> |
| Runtime validation | <health/smoke/observability> | <present|needs update|missing|not applicable|blocked> | <file/ticket/action> | <blocking|required|advisory|N/A> | <owner or unknown> |
| AI workstream validation | <instructions/commands/skills> | <present|needs update|missing|not applicable|blocked> | <file/ticket/action> | <blocking|required|advisory|N/A> | <owner or unknown> |
```

## Ecosystem Terraform Report

```md
Ecosystem terraform result:
- Workflow: <roadmap-terraform|tech-terraform|assess-then-harden>
- Artifacts created: <list or "None">
- Artifacts updated: <list or "None">
- Proposed only: <list or "None">
- External mutations: <performed|blocked|not requested>
- Questions asked: <answered/deferred/defaulted summary>
- Capabilities: <verified/blocked/not used>
- Sources inspected: <summary>
- Tickets: <created/updated/proposed/canceled/blocked counts>
- Quality layer matrix: <present/needs update/missing/not applicable/blocked summary, required for tech-terraform>
- Quality gates: <passed/failed/blocked/skipped/not run>
- Approval gates remaining: <list or "None">
- Residual risk: <risk or "None identified">
- Next action: <smallest useful step>
```

## PR Body

```md
## Problem

<what this change addresses>

## Approach

<what changed and why>

## Changed Surface

- <area/file>

## Validation

- <command>: <status>

## Deployment / Operations

<impact, migration, env, monitoring, or N/A>

## Rollback

<how to revert or contain>

## Residual Risk

<known gaps or "None identified">
```

## Skill Template

```md
---
name: <skill-name>
description: <when this skill must be used>
---

# <Skill Name>

## Trigger

Use this skill when...

## Workflow

1. ...
2. ...
3. ...

## Guardrails

- ...

## Output

Report...
```

## Repo Adoption Verification Prompt

```text
List the instruction layers you can see for this repository.
For each layer, summarize the rules you will apply.
State whether CONFIG_KIT_AI_PROMPT.md was loaded.
State which manifest file you loaded.
State the active harness capability record.
State whether session journaling is required.
State which validation commands are required for code changes.
Do not edit files.
```

## Config Kit Ingestion Prompt

```text
Absorb the provided Agent Configuration Framework before doing substantial work.

Read CONFIG_KIT_AI_PROMPT.md if available. Then read AI_BOOTSTRAP.md and FRAMEWORK_MANIFEST.md first, followed by the task-relevant framework files and repo-local instructions.

Build an active instruction model:
- Source-of-truth order.
- Repo-local rules.
- Harness capabilities.
- Workflow track.
- Quality gates.
- Quality convergence triggers.
- Breakpoints.
- Stop conditions.
- Validation plan.

Before implementation, report loaded files, missing required files, capability gaps, conflicts, plan, and smallest safe next step.
```

## Agent Delegation Brief

```md
Task:
<specific bounded objective>

Scope:
<files/modules/areas owned by this agent>

Do not touch:
<files/modules/areas outside scope>

Context:
<source-of-truth details needed>

Authorization:
<include only for directive/planning/architecture/challenge briefs>

Allowed outputs:
<exact output shape and forbidden output>

Success criteria:
<what must be true when done>

Validation:
<commands, checks, or evidence required>

Escalation conditions:
<when to stop and return control to the master>

Expected output:
<findings, patch summary, changed files, validation>

Coordination:
You are not alone in the codebase. Do not revert or overwrite changes outside your scope. Adapt to nearby changes.
```
