# Continuous Skill Learning

Continuous skill learning turns repeated agent lessons into durable shared behavior without copying closed-scope details.

The goal is not to create endless documentation. The goal is to put each lesson in the narrowest durable layer where future agents will actually use it.

## Learning Triggers

Consider updating the framework when:

- The same instruction is repeated in multiple tasks.
- A recurring mistake causes rework.
- A review finding reveals a missing standard.
- A validation failure could have been prevented by a gate.
- A source-of-truth conflict required a policy decision.
- A repo pattern is stable enough to document.
- A manual checklist becomes reliable enough to automate.

## Challenge Before Promotion

Before promoting any lesson into a directive, skill, template, or automation,
challenge it for hidden confounders, causal overfitting, drift, current
source-of-truth fit, and industry-quality alignment. Journals, memories, cached
conclusions, and prior project patterns are evidence to test, not authority to
copy. Promote the narrowest rule that survives current evidence.

## Promotion Ladder

Promote lessons to the narrowest useful place:

1. Current final response.
   - Use for one-time observations.

2. Session journal.
   - Use for task-local facts and resumability.

3. Framework manifest.
   - Use for file inventory, load profiles, adoption readiness, and harness capability records.

4. Repo instruction file.
   - Use for repo architecture, validation, release, and workflow rules.

5. Repo-local skill.
   - Use for repeated workflows in one repo.

6. Parent instruction file.
   - Use for conventions shared across several repos in one workspace.

7. Global skill.
   - Use for workflows that should apply across many repos.

8. Global instruction file.
   - Use for universal collaboration and execution behavior.

9. Automated gate.
   - Use when the rule can be checked reliably by lint, tests, CI, scripts, or static analysis.

## Decision Matrix

| Lesson Type | Best Home |
| --- | --- |
| Collaboration preference | Global instruction |
| Framework file inventory or load profile | Framework manifest |
| Debugging workflow | Global skill |
| Architecture boundary | Repo instruction |
| Repeated repo workflow | Repo-local skill |
| Validation command | Repo instruction or CI |
| Formatting rule | Formatter or lint |
| Security invariant | Repo instruction plus tests or CI |
| Review checklist | Review framework or skill |
| Temporary task context | Session journal |

## Skill Update Workflow

1. Identify the repeated behavior.
2. Remove closed-scope details.
3. Write the trigger clearly.
4. Write the workflow as ordered steps.
5. Add guardrails.
6. Add output expectations.
7. Check for overlap with existing skills.
8. Ask for approval before changing shared skills.
9. For Codex skills, refresh the Skill Library Router index when the router is installed, or record why indexing is blocked or not applicable.
10. Verify a future agent can apply the skill from the file alone.

## Rule Update Workflow

When a repo rule changes:

1. Update the repo instruction file.
2. Update any repo-local skill that repeats the rule.
3. Update lint, tests, CI, or scripts if enforceable.
4. Update contributor docs if humans need the same rule.
5. Record the change in the journal or PR body.

## Automation Decision

Before adding automation, ask:

- Is the rule objective enough to check?
- Will false positives be low?
- Will the tool be maintained?
- Can the rule run quickly enough for normal workflow?
- Does automation avoid closed-scope leakage?

If not, keep it as a review criterion.

## Anti-Patterns

- Putting repo-specific rules into global skills.
- Creating multiple skills with overlapping triggers.
- Adding scripts that no one will maintain.
- Capturing closed-scope examples in a shared skill.
- Treating memory or journals as a replacement for current file inspection.
- Promoting a one-off preference into a global rule.
