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
- Model routing: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
- Cache or memory: <available|limited|blocked|unavailable|unknown> - <evidence and fallback>
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
- Journaling: <required|optional|disabled and path>
- Required validation: <commands or "not defined">
- Closed-scope scan: <passed|failed|not run>
- First-session check: <passed|failed|not run>
- Archive updated: <yes|no|not applicable>

Gaps:
- <gap or "None identified">

Next action:
- <smallest useful next step>
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
